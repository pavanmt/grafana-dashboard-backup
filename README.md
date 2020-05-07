## Introduction
This project is an initiative to overcome the DevOps manual tedious efforts to take up the snapshot backups in an automated way. A Python based application to help in taking backup of Grafana Dashboard snapshot as JSON via interacting with Grafana API. This backup script can be run locally or through Kubernetes cron job.

## Features
* Easily backup, restore, and create Grafana Dashboards.
* Have versioned backups for restoring and saving to S3 bucket.
* Supports S3 and PV storage with configurable backup folder and backup strategy.
* Multithreading support for faster execution
* Smart revision history backup using last version validation from meta_data

## Deployment Steps
Below are the set of kubectl commands need to be run to setup the Grafana Backup Application on to the Kubernetes cluster.

* Create Namespace

```
kubectl create ns gb
```

* Modify the grafana_urls.json file to contain all the grafana dashboard urls and editor role api key to enable application to take backup.

```
kubectl create secret generic grafana-config-secret -n gb --from-file=src/grafana_urls.json
```

* Deploy Storage and PVC manifest

```
kubectl apply -f packager/pvc_gb.yaml -n gb
```

* Modify the docker image version in the below manifest files as per the version file and then deploy the cronjobs for hourly, daily and revision history backup. Daily backup is scheduled at 10:00 PM and Revision history backup at 8:00 PM respectively.

```
kubectl apply -f packager/cron_gb_daily.yaml -n gb
kubectl apply -f packager/cron_gb_hourly.yaml -n gb
kubectl apply -f packager/cron_gb_rb.yaml -n gb
```


## Deployment Validation

After the application is deployed on a Kubernetes cluster follow below instruction to watch deployment status.

* CronJob Status

```
kubectl get cronjobs -n gb
NAME                   SCHEDULE       SUSPEND   ACTIVE   LAST SCHEDULE   AGE
grafanabackup-daily    * 22 * * *     False     0        10m             11h
grafanabackup-hourly   */60 * * * *   False     0        10m             11h
grafanabackup-rb       * 20 * * *     False     0        10m             11h
```

* Pod creation status

```
kubectl get pods -n gb
NAME                                    READY   STATUS      RESTARTS   AGE
grafanabackup-daily-1588831200-6w4vs    0/1     Completed   0          12m
grafanabackup-hourly-1588831200-jmbzk   0/1     Completed   0          12m
grafanabackup-rb-1588831200-ck88r       0/1     Completed   0          12m
```
* POD Logs

```
kubectl logs grafanabackup-hourly-1588834800-m7jz4 -n gb

[2020-05-07T07:00:48] INFO [MainThread] [grafana_backup.py:backup_grafana_dashboard:327] Running Grafana Backup script!
[2020-05-07T07:00:48] INFO [MainThread] [grafana_backup.py:__init__:37] Local backup is enabled and storing under : /backup/
[2020-05-07T07:00:52] INFO [MainThread] [grafana_backup.py:__init__:42] s3 backup is enabled for bucket s3-aws-bucket and storing under : grafana/backup/
[2020-05-07T07:00:52] INFO [Thread-1] [grafana_backup.py:__s3_store:47] Storing data : grafana/backup/hourly/gfbk/.meta_data
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__store:250] Storing data on folder : /backup/hourly/gfbk/
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:_store_meta_info:242] Taking Hourly Grafana JSON file Backup for host Gfbk.
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_sdk.py:search_db:23] Request To : URL http://172.20.52.160/api/search?type=dash-db
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:dashboard_backup:90] Scanned data for backup - 4
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_sdk.py:dashboard_details:46] Request To : URL http://172.20.52.160/api/dashboards/uid/FMpe9L6Wk
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__s3_store:47] Storing data : grafana/backup/hourly/gfbk/neondb_fmpe9l6wk.json
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__store:250] Storing data on folder : /backup/hourly/gfbk/
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_sdk.py:dashboard_details:46] Request To : URL http://172.20.52.160/api/dashboards/uid/2ExQrYeWz
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__s3_store:47] Storing data : grafana/backup/hourly/gfbk/pavantestdashboard_2exqryewz.json
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__store:250] Storing data on folder : /backup/hourly/gfbk/
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_sdk.py:dashboard_details:46] Request To : URL http://172.20.52.160/api/dashboards/uid/cdATDaeWz
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__s3_store:47] Storing data : grafana/backup/hourly/gfbk/testingdashboar_cdatdaewz.json
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__store:250] Storing data on folder : /backup/hourly/gfbk/
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_sdk.py:dashboard_details:46] Request To : URL http://172.20.52.160/api/dashboards/uid/fX41v-6Zk
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__s3_store:47] Storing data : grafana/backup/hourly/gfbk/visualdb_fx41v-6zk.json
[2020-05-07T07:00:53] INFO [Thread-1] [grafana_backup.py:__store:250] Storing data on folder : /backup/hourly/gfbk/
[2020-05-07T07:00:53] INFO [MainThread] [grafana_backup.py:backup_grafana_dashboard:343] Completed taking Grafana JSON Backup!
```
* Grafana Backup Validation
```
# Hourly Backup Folder

  S3:
  <bucket_name>/grafana/backup/hourly/<host_name>/<dbname>_<uid>.json
  PV:
  <backup_folder_name>/hourly/<host_name>/<dbname>_<uid>.json

# Daily Backup Folder

  S3:
  <bucket_name>/grafana/backup/daily/<DD-MM-YYYY>/<host_name>/<dbname>_<uid>.json
  PV:
  <backup_folder_name>/daily/<DD-MM-YYYY>/<host_name>/<dbname>_<uid>.json

# Revision Backup Folder

  S3:
  <bucket_name>/grafana/backup/revision/<host_name>/<dbname>_<uid>.json
  PV:
  <backup_folder_name>/revision/<host_name>/<dbname>_<uid>.json
```

* S3 bucket folder structure snapshot

![s3_bucket](https://user-images.githubusercontent.com/5840018/81284337-9b5a8780-907b-11ea-8e4f-3308c43c8acd.png)


## Running Script Locally
The Grafana backup script can be run locally to explore few other features which are not part of cronjobs like create and restore dashboards. The

### Pre-requisites

* To run the scripts locally ensure python3 is installed and application dependency python modules are installed using pip

```
pip install -r requirements.txt
```

* Make sure details of grafana_urls.json file is set correctly. The S3 and PV storage details are configurable and can be enabled or disabled based on the flag enabled from the file, look for the backup files generated as per folder name set in the file.

### Script Usage

* Grafana dashboard backup

```
# Hourly Backup:
python grafana_backup.py -b hourly -conf grafana_urls.json

# Daily Backup:
python grafana_backup.py -b hourly -conf grafana_urls.json

# Both Hourly and Daily Backup:
python grafana_backup.py -b both -conf grafana_urls.json
```

* Grafana revision history backup

```
# To run on all hosts
python grafana_backup.py -rb all -conf grafana_urls.json

# Running on selected urls
python grafana_backup.py -rb preprod staging  -conf grafana_urls.json
```

* To create new dashboard from existing backup snapshot

```
# To run on all hosts
python grafana_backup.py -c all -conf grafana_urls.json

# Running on selected urls and selected dashboard
python grafana_backup.py -c preprod staging -db_uid test_sk2k2 test1_s1kk2 -conf grafana_urls.json

# Note:
# db_uid is a json file name obtained from backup folders <dbname>_<uid>.json
```

* To restore dashboard from existing backup snapshot

```
# To run on all hosts
python grafana_backup.py -r all -conf grafana_urls.json

# Running on selected urls and selected dashboard
python grafana_backup.py -r preprod staging -db_uid test_sk2k2 test1_s1kk2 -conf grafana_urls.json

# Note:
# db_uid is a json file name obtained from backup folders <dbname>_<uid>.json
```

Note:<br/>
grafana_urls.json file content key grafana_urls is any array, set all the list of urls with unique name, url and api keys to enable Grafana backup script application to take backup periodically.
