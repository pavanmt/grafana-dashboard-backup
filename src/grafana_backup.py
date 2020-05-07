import sys
import os
import json
import grafana_sdk
import argparse
import multiprocessing
import glob
import boto3
from datetime import datetime
from multiprocessing.pool import ThreadPool

hourly_backup_type = "hourly"
daily_backup_type = "daily"
revision_folder = "revision"
pool = ThreadPool(processes=multiprocessing.cpu_count()-1)

class GrafanaBackupManager:

    grafana_config = "grafana_urls.json"
    config_path = "/config/"

    def __init__(self, name, grafana_url, api_key):
        self.s3 = True
        self.name = name
        current_date = datetime.now().strftime("%d-%m-%Y")
        self.hourly_folder = "hourly/"+self.name+"/"
        self.daily_folder = "daily/{}/".format(current_date)+self.name+"/"
        self.grafana_api = grafana_sdk.GrafanaApi(grafana_url, api_key)
        if os.path.exists(GrafanaBackupManager.grafana_config) == True:
            grafana_config_content = GrafanaBackupManager.get_grafana_content(GrafanaBackupManager.grafana_config)
            s3_backup_content = grafana_config_content['backup'].get('s3', dict())
            local_backup_content = grafana_config_content['backup'].get('local', dict())
            self.local = local_backup_content.get('enabled', True) == True
            self.s3 = s3_backup_content.get('enabled', False) == True
            if self.local:
                self.backup_folder = local_backup_content.get('backup_folder', '')
                grafana_sdk.get_logger().info("Local backup is enabled and storing under : {} ".format(self.backup_folder))
            if self.s3:
                self.s3_ins = boto3.resource('s3')
                self.s3_bucket_name = s3_backup_content['bucket_name']
                self.s3_backup_folder = s3_backup_content.get('backup_folder','grafana/backup/')
                grafana_sdk.get_logger().info("s3 backup is enabled for bucket {} and storing under : {}".format(self.s3_bucket_name, self.s3_backup_folder))


    def __s3_store(self, filename, content):
        try:
            grafana_sdk.get_logger().info("Storing data : {}".format(self.s3_backup_folder+filename))
            self.s3_ins.Object(self.s3_bucket_name, self.s3_backup_folder+filename).put(Body=json.dumps(content))
        except Exception as exc:
            grafana_sdk.get_logger().error("Error storing backup on s3 {}, {}, error : {}".format(self.s3_bucket_name, filename, str(exc)))


    def __s3_read(self, filename):
        try:
            s3_object_content = self.s3_ins.Object(self.s3_bucket_name, filename).get()["Body"].read().decode('utf-8')
            return json.loads(s3_object_content)
        except Exception as exc:
            grafana_sdk.get_logger().error("Error reading s3 {}, {}, error : {}".format(self.s3_bucket_name, filename, str(exc)))
            raise Exception("Error reading s3 bucket "+self.s3_bucket_name)

    def __get_folder_name(self, folder_name):
        if self.s3:
            folder_name =  self.s3_backup_folder+folder_name
        elif self.local:
            folder_name =  self.backup_folder+folder_name
        return folder_name


    def __scan_folders(self, folder_name, filename):
        if self.s3:
            backup_file_list = []
            bucket = self.s3_ins.Bucket(name=self.s3_bucket_name)
            folder_name = self.__get_folder_name(folder_name)
            if filename != "*.json":
                folder_name = folder_name + filename
            for obj in bucket.objects.filter(Prefix=folder_name):
                if not obj.key.endswith(".meta_data"):
                    backup_file_list.append(obj.key)
            return backup_file_list
        if self.local:
            folder_name = self.__get_folder_name(folder_name)
        return glob.glob(folder_name+filename)

    def dashboard_backup(self, folder_name):
        try:
            dashboards = self.grafana_api.search_db()
            if len(dashboards)==0:
                grafana_sdk.get_logger().error("Could not find any data for backup under {}".format(folder_name))
            else:
                grafana_sdk.get_logger().info("Scanned data for backup - {}".format(len(dashboards)))
            for dashboard in dashboards:
                dashboard_uri = dashboard['uid']
                dashboard_title = dashboard['title'].replace(" ","")
                dashboard_details_json = self.grafana_api.dashboard_details(dashboard_uri)
                self.__store(folder_name, "{}_{}.json".format(dashboard_title.lower(), dashboard_uri.lower()), dashboard_details_json)
        except Exception as exc:
            grafana_sdk.get_logger().error("Error taking backup {}, error : {}".format(folder_name, str(exc)))

    def __scan_to_restore(self, folder_name, filename):
        backup_file_list = self.__scan_folders(folder_name, filename)
        if len(backup_file_list)==0:
            grafana_sdk.get_logger().error("Could not find any data for restore under {}".format(folder_name))
        else:
            grafana_sdk.get_logger().info("Scanned data for restore - {}".format(backup_file_list))
        for backup_file in backup_file_list:
            dashboard_content_json = self.get_backup_meta_content(backup_file)
            dashboard_content_json['message'] = "Updated by grafana backup script with content {}.".format(backup_file)
            dashboard_content_json['overwrite'] = True
            self.grafana_api.restore(json.dumps(dashboard_content_json))

    def __scan_to_revision(self, name, db_names=None):
        search_db_response = self.grafana_api.search_db()
        if len(search_db_response)==0:
            grafana_sdk.get_logger().error("Could not find any revision files for host {}".format(name))
        else:
            grafana_sdk.get_logger().info("Scanned data for revison - {}".format(len(search_db_response)))
        for db_response in search_db_response:
            db_id = db_response['id']
            db_uid = db_response['uid']
            db_title = db_response['title'].replace(" ","")
            meta_version = self.__get_revision_meta("{}/{}/{}_{}/".format(revision_folder, name, db_title.lower(), db_uid.lower()))
            ver = [1] if  not meta_version else [meta_version]
            if not db_names or db_uid.lower() in db_names:
                db_title = db_response['title'].replace(" ","")
                dashboard_versions = self.grafana_api.dashboard_versions(db_id)
                for dashboard_version in dashboard_versions:
                    dashboard_version_id = dashboard_version['version']
                    if not meta_version or int(meta_version)<int(dashboard_version_id):
                        dashboard_version_details = self.grafana_api.dashboard_version_details(db_id, dashboard_version_id)
                        self.__store("{}/{}/{}_{}/".format(revision_folder, name, db_title.lower(), db_uid.lower()), "version{}.json".format(dashboard_version_id), dashboard_version_details)
                        ver.append(int(dashboard_version_id))
            self.__store_revision_meta("{}/{}/{}_{}/".format(revision_folder, name, db_title.lower(), db_uid.lower()), max(ver))

    def __scan_to_create(self, folder_name, file_name):
        backup_file_list = self.__scan_folders(folder_name, file_name)
        if len(backup_file_list)==0:
            grafana_sdk.get_logger().error("Could not find any data to create under {}".format(folder_name))
        else:
            grafana_sdk.get_logger().info("Scanned data to create db - {}".format(backup_file_list))
        for backup_file in backup_file_list:
            dashboard_content_json = self.get_backup_meta_content(backup_file)
            folder_id = dashboard_content_json['meta']['folderId']
            folder_title = dashboard_content_json['meta']['folderTitle']
            if folder_id != 0:
                folder_response = self.grafana_api.search_folder(folder_id)
                if folder_response.status_code!=200:
                    new_folder_response = self.grafana_api.create_folder(folder_title)
                    folder_id = new_folder_response['id']
                else:
                    folder_response = folder_response.json()
                    folder_id = folder_response['id']
            del dashboard_content_json['dashboard']['uid']
            del dashboard_content_json['dashboard']['id']
            dashboard_content_json['folderId'] = folder_id
            dashboard_content_json['message'] = "Updated by grafana backup script with content {}.".format(backup_file)
            dashboard_content_json['overwrite'] = True
            self.grafana_api.restore(json.dumps(dashboard_content_json))

    def revision_dashboard_backup(self, name, dashboard_names):
        grafana_sdk.get_logger().info("taking revision backup of dashboard on host {}, dashboard {}".format(name, dashboard_names))
        try:
            all_dashboard = "all" in dashboard_names
            if all_dashboard:
                self.__scan_to_revision(name)
            else:
                self.__scan_to_revision(name, dashboard_names)
        except Exception as exc:
            grafana_sdk.get_logger().error("Error taking revision backup {}, error : {}".format(name, str(exc)))

    def create_dashboard(self, name, dashboard_names, rfrom):
        grafana_sdk.get_logger().info("Creating dashboard on host {}, dashboard {}, from {}".format(name, dashboard_names, rfrom))
        all_dashboard = "all" in dashboard_names
        try:
            if rfrom == hourly_backup_type:
                if all_dashboard:
                    folder_name = "hourly/{}/".format(name)
                    self.__scan_to_create(folder_name, "*.json")
                else:
                    for dashboard_name in dashboard_names:
                        folder_name = "hourly/{}/".format(name)
                        self.__scan_to_create(folder_name, "{}.json".format(dashboard_name))
            else:
                if all_dashboard:
                    folder_name = "daily/{}/{}/".format(rfrom, name)
                    self.__scan_to_create(folder_name, "*.json")
                else:
                    for dashboard_name in dashboard_names:
                        folder_name = "daily/{}/{}/".format(rfrom, name)
                        self.__scan_to_create(folder_name, "{}.json".format(dashboard_name))
        except Exception as exc:
            grafana_sdk.get_logger().error("Error creating dashboard {}, error : {}".format(name, str(exc)))

    def restore_dashboard(self, name, dashboard_names, rfrom):
        grafana_sdk.get_logger().info("Restoring host {}, dashboard {}, from {}".format(name, dashboard_names, rfrom))
        try:
            all_dashboard = "all" in dashboard_names
            if rfrom == hourly_backup_type:
                if all_dashboard:
                    folder_name = "hourly/{}/".format(name)
                    self.__scan_to_restore(folder_name, "*.json")
                else:
                    for dashboard_name in dashboard_names:
                        folder_name = "hourly/{}/".format(name)
                        self.__scan_to_restore(folder_name, "{}.json".format(dashboard_name))
            else:
                if all_dashboard:
                    folder_name = "daily/{}/".format(rfrom)
                    self.__scan_to_restore(folder_name, "*.json")
                else:
                    for dashboard_name in dashboard_names:
                        folder_name = "daily/{}/{}".format(rfrom, dashboard_name)
                        self.__scan_to_restore(folder_name, "{}.json".format(dashboard_name))
        except Exception as exc:
            grafana_sdk.get_logger().error("Error restoring dashboard {}, error : {}".format(name, str(exc)))

    def hourly_backup(self):
        self._store_meta_info(hourly_backup_type)
        self.dashboard_backup(self.hourly_folder)

    def daily_backup(self):
        self._store_meta_info(daily_backup_type)
        self.dashboard_backup(self.daily_folder)

    def __store_revision_meta(self, folder_name, version):
        meta_data = {'version': version}
        self.__store(folder_name, ".meta_data", meta_data)

    def __get_revision_meta(self, folder_name):
        try:
            return self.get_backup_meta_content("{}.meta_data".format(self.__get_folder_name(folder_name)))['version']
        except:
            grafana_sdk.get_logger().info("Revision meta data file is not present.")
            return None

    def _store_meta_info(self, backup_type, mode="Auto"):
        meta_data = {'time':datetime.now().strftime("%d-%m-%Y %H:%M:%S"), 'type': backup_type, 'mode': mode}
        if backup_type == daily_backup_type:
            folder_name = self.daily_folder
        else:
            folder_name = self.hourly_folder
        self.__store(folder_name, ".meta_data", meta_data)
        grafana_sdk.get_logger().info("Taking {} Grafana JSON file Backup for host {}.".format(backup_type.title(), self.name.title()))

    def __store(self, folder_name, file_name, response):
        if self.s3:
            self.__s3_store(folder_name+file_name, response)
        try:
            if self.local:
                folder_name = self.backup_folder+folder_name
                grafana_sdk.get_logger().info("Storing data on folder : {}".format(folder_name))
                os.makedirs(folder_name, exist_ok = True)
                with open(folder_name+file_name,'w') as fp:
                    json.dump(response, fp, indent=4, sort_keys=True)
                fp.close()
        except Exception as exc:
            grafana_sdk.get_logger().error("Error storing backup localy error : {}".format(str(exc)))

    def get_backup_meta_content(self, file_name):
        if self.s3:
            return self.__s3_read(file_name)
        return GrafanaBackupManager.get_grafana_content(file_name)

    @staticmethod
    def get_grafana_content(file_name):
        try:
            grafana_url_file = open(file_name)
            grafana_url_data = json.load(grafana_url_file)
            grafana_url_file.close()
            return grafana_url_data
        except Exception as exc:
            grafana_sdk.get_logger().error("error reading file {} , error {}".format(file_name, str(exc)))

def get_grafana_mapper(grafana_url):
    try:
        name = grafana_url['name']
        url = grafana_url['url']
        api_key = grafana_url['api_key']
        return name, url, api_key
    except Exception as exc:
        grafana_sdk.get_logger().error("error mapping grafana host config file, {}".format(str(exc)))
        sys.exit(0)

def revison_grafana_backup(revision_hosts=["all"], dashboard_names=["all"]):
    grafana_sdk.get_logger().info("Running Grafana Revision script!")
    all_hosts = "all" in revision_hosts
    for grafana_url in GrafanaBackupManager.get_grafana_content(GrafanaBackupManager.grafana_config)['grafana_urls']:
        name, url, api_key = get_grafana_mapper(grafana_url)
        if all_hosts or name in revision_hosts:
            gbm = GrafanaBackupManager(name, url, api_key)
            pool.apply_async(gbm.revision_dashboard_backup, (name, dashboard_names))
        else:
            grafana_sdk.get_logger().info("could not find host - {} in {}!".format(name, revision_hosts))
    pool.close()
    pool.join()
    grafana_sdk.get_logger().info("Completed running Grafana Revision!")

def create_grafana_dashboard(create_hosts=["all"], dashboard_names=["all"], rfrom=hourly_backup_type):
    grafana_sdk.get_logger().info("Running Grafana Create script!")
    all_hosts = "all" in create_hosts
    for grafana_url in GrafanaBackupManager.get_grafana_content(GrafanaBackupManager.grafana_config)['grafana_urls']:
        name, url, api_key = get_grafana_mapper(grafana_url)
        if all_hosts or name in create_hosts:
            gbm = GrafanaBackupManager(name, url, api_key)
            pool.apply_async(gbm.create_dashboard, (name, dashboard_names, rfrom))
        else:
            grafana_sdk.get_logger().info("could not find host - {} in {}!".format(name, create_hosts))
    pool.close()
    pool.join()
    grafana_sdk.get_logger().info("Completed running Grafana Create!")

def restore_grafana_dashboard(restore_hosts=["all"], dashboard_names=["all"], rfrom=hourly_backup_type):
    grafana_sdk.get_logger().info("Running Grafana Restore script!")
    all_hosts = "all" in restore_hosts
    for grafana_url in GrafanaBackupManager.get_grafana_content(GrafanaBackupManager.grafana_config)['grafana_urls']:
        name, url, api_key = get_grafana_mapper(grafana_url)
        if all_hosts or name in restore_hosts:
            gbm = GrafanaBackupManager(name, url, api_key)
            pool.apply_async(gbm.restore_dashboard, (name, dashboard_names, rfrom))
        else:
            grafana_sdk.get_logger().info("could not find host - {} in {}!".format(name, restore_hosts))
    pool.close()
    pool.join()
    grafana_sdk.get_logger().info("Completed running Grafana Restore!")


def backup_grafana_dashboard(backup_type):
    grafana_sdk.get_logger().info("Running Grafana Backup script!")
    for grafana_url in GrafanaBackupManager.get_grafana_content(GrafanaBackupManager.grafana_config)['grafana_urls']:
        name, url, api_key = get_grafana_mapper(grafana_url)
        gbm = GrafanaBackupManager(name, url, api_key)
        try:
            if backup_type == hourly_backup_type:
                pool.apply_async(gbm.hourly_backup, ())
            elif backup_type == daily_backup_type:
                pool.apply_async(gbm.daily_backup, ())
            else:
                pool.apply_async(gbm.hourly_backup, ())
                pool.apply_async(gbm.daily_backup, ())
        except Exception as e:
            grafana_sdk.get_logger().error("Error running backup tasks : {}".format(str(e)))
    pool.close()
    pool.join()
    grafana_sdk.get_logger().info("Completed taking Grafana JSON Backup!")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Grafana backup script.')
    parser.add_argument('-b','--backup', type=str, choices=['hourly', 'daily', 'both'], help="backup type needed for script to invoke backup.")
    parser.add_argument('-r', '--restore', type=str, metavar='N', nargs='+', help="restore grafana hostname, \"all\" to restore all grafana urls.")
    parser.add_argument('-c', '--create', type=str, metavar='N', nargs='+', help="create grafana db for hostname, specify \"all\" to create db of all grafana urls.")
    parser.add_argument('-rb','--revision_backup', type=str, metavar='N', nargs='+', help="revison backup, specify \"all\" to take backup of all grafana urls.")
    parser.add_argument('-db_uid', '--dashboard_uid', default=["all"], type=str, metavar='N', nargs='+', help="restore/create/revision grafana dashboard uid, \"all\" for all grafana dashboard.")
    parser.add_argument('-rfrom', '--restore_from', type=str, default="hourly", help="Used with restore option, either pass hourly or date eg: 28-4-2020")
    parser.add_argument('-conf', '--config_file', type=str, default=GrafanaBackupManager.grafana_config, help="full path to grafana config file.")
    params = parser.parse_args()
    backup = params.backup
    restore_hosts = params.restore
    create_hosts = params.create
    dashboard_names = params.dashboard_uid
    restore_from = params.restore_from
    revision_hosts = params.revision_backup
    config_file = params.config_file

    #convert to lowercases
    if restore_hosts:
        restore_hosts = [restore_host.lower() for restore_host in restore_hosts]

    if dashboard_names:
        dashboard_names = [dashboard_name.lower() for dashboard_name in dashboard_names]

    if revision_hosts:
        revision_hosts = [revision_host.lower() for revision_host in revision_hosts]

    #set configuration file from params
    if config_file:
        GrafanaBackupManager.grafana_config = config_file
    elif os.path.exists(GrafanaBackupManager.grafana_config) == False:
        GrafanaBackupManager.grafana_config = GrafanaBackupManager.config_path+GrafanaBackupManager.grafana_config

    if backup:
        backup_grafana_dashboard(backup.lower())
    elif restore_hosts:
        restore_grafana_dashboard(restore_hosts, dashboard_names, restore_from)
    elif create_hosts:
        create_grafana_dashboard(create_hosts, dashboard_names, restore_from)
    elif revision_hosts:
        revison_grafana_backup(revision_hosts, dashboard_names)
    else:
        parser.print_help()
        sys.exit(0)
