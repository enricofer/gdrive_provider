# -*- coding: utf-8 -*-
"""
/***************************************************************************
                                 A QGIS plugin
 A plugin for using Google drive sheets as QGIS layer shared between concurrent users
 portions of code are from https://github.com/g-sherman/pseudo_csv_provider
                              -------------------
        begin                : 2015-03-13
        git sha              : $Format:%H$
        copyright            : (C)2017 Enrico Ferreguti (C)2015 by GeoApt LLC gsherman@geoapt.com
        email                : enricofer@gmail.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from __future__ import print_function
from __future__ import absolute_import

from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import range
from builtins import object
__author__ = 'enricofer@gmail.com'
__date__ = '2017-03-24'
__copyright__ = 'Copyright 2017, Enrico Ferreguti'


#QT specific
from qgis.PyQt.QtCore import QSettings

#QGIS specific
from qgis.core import QgsMessageLog, NULL

#Standard modules
import httplib2
import httplib2shim
import requests
import os
import io
import csv
import collections
import json
import base64
import hashlib
import zlib
from string import ascii_uppercase

#Google API
from apiclient import discovery
from apiclient.http import MediaFileUpload, MediaIoBaseUpload
from oauth2client import client, GOOGLE_TOKEN_URI
from oauth2client import tools
from oauth2client.file import Storage

#Plugin modules
from .utils import slugify


logger = lambda msg: QgsMessageLog.logMessage(msg, 'Googe Drive Provider', 1)

def int_to_a1(n):
    if n < 1:
        return ''
    if n < 27:
        return ascii_uppercase[n-1]
    else:
        q, r = divmod(n, 26)
        return int_to_a1(q) + ascii_uppercase[r-1]

def pack(content):
    return base64.b64encode(zlib.compress(content.encode("utf-8"))).decode('utf-8')

def unpack(zipped_content):
    return zlib.decompress(base64.b64decode(zipped_content)).decode("utf-8")

class google_authorization(object):
    def __init__(self, parentClass, scopes, credential_dir, application_name, client_id, client_secret_file = 'client_secret.json' ):
        # fix_print_with_import
        print("authorizing:",client_id, application_name, credential_dir)
        self.parent = parentClass
        self.credential_dir = os.path.abspath(credential_dir)
        if not os.path.exists(credential_dir):
            os.makedirs(credential_dir)
        self.credential_path = os.path.join(credential_dir,client_id.split("@")[0]+"_"+slugify(application_name)+'.json')
        self.secret_path = os.path.join(self.credential_dir,client_secret_file)
        self.store = Storage(self.credential_path)
        self.scopes = scopes
        self.client_id = client_id
        self.application_name = application_name
        self.proxyConnection()
        self.ghdbtoken = unpack('eJxLz89Pzyy2skwytTRPSTYySEw0sDQ2TjJKTkxLSjYzTkkzSDQ3MU81Nko1S7RMswQAZE8ORA==')

        try:
            import argparse
            parser = tools.argparser
            #parser = ArgumentParser(prog='', usage=None, description=None, version=None, formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=False)
            try:
                self.flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
            except:
                self.flags = argparse.Namespace(auth_host_name='localhost', auth_host_port=[8080, 8090], logging_level='ERROR', noauth_local_webserver=False)
            #self.flags = argparse.ArgumentParser(prog='', usage=None, description=None, version=None, add_help=False).parse_args()
            # fix_print_with_import
            print("self.flags",self.flags)
        except ImportError:
            self.flags = None
    

    def proxyConnection(self):      
        s = QSettings()
        proxyEnabled = s.value("proxy/proxyEnabled", "")
        proxyType = s.value("proxy/proxyType", "" )
        proxyHost = s.value("proxy/proxyHost", "" )
        proxyPort = s.value("proxy/proxyPort", "" )
        proxyUser = s.value("proxy/proxyUser", "" )
        proxyPassword = s.value("proxy/proxyPassword", "" )
        print ("proxySettings",proxyEnabled,type(proxyEnabled),proxyType,type(proxyType))
        if proxyEnabled and proxyType == 'HttpProxy': # test if there are proxy settings
            self.proxyConf = httplib2.ProxyInfo(httplib2.socks.PROXY_TYPE_HTTP_NO_TUNNEL, proxyHost, int(proxyPort), proxy_user = proxyUser, proxy_pass = proxyPassword)
            proxy_url = "http://{}:{}@{}:{}".format(proxyUser,proxyPassword,proxyHost,proxyPort)
            self.proxyDict = {
                "http"  : proxy_url,
                "https" : proxy_url 
            }
            for var in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy",]:
                os.environ[var] = proxy_url
            print("proxyOK", self.proxyDict)
        else:
            self.proxyConf =  None
            self.proxyDict = None

    def get_credentials(self):
        """Gets valid user credentials from storage.

        If nothing has been stored, or if the stored credentials are invalid,
        the OAuth2 flow is completed to obtain the new credentials.

        Returns:
            Credentials, the obtained credential.
        """

        credentials = self.store.get()
        if not credentials or credentials.invalid:
            flow = client.flow_from_clientsecrets(self.secret_path, self.scopes, message='Invalid secret or credentials')
            # fix_print_with_import
            print("FLOW",flow)
            flow.user_agent = self.application_name
            try:
                if self.flags:
                    credentials = tools.run_flow(flow, self.store, self.flags)
                else: # Needed only for compatibility with Python 2.6
                    credentials = tools.run(flow, self.store)
                # fix_print_with_import
                print("credentials.invalid", credentials.invalid)
                logger( 'Storing credentials to ' + self.credential_path)
            except:
                return None
        return credentials

    def getProxyDict(self):
        return self.proxyDict

    def authorize(self):
        self.httpConnection = httplib2shim.Http(ca_certs=os.path.join(self.credential_dir,'cacerts.txt'), timeout=8) #proxy_info = self.proxyConf,
        auth = self.get_credentials()
        if auth:
            return auth.authorize(self.httpConnection)
        else:
            return None

class ex_service_github(object):
    repo = 'googis_public_layers'
    username = 'googis'
    storage = 'public_metadata'
    api_url = 'https://api.github.com'

    def __init__(self,credentials,DB='metadata_DB'):
        '''
        The class is a convenience wrapper to google drive python module
        :param credentials:
        '''
        self.credentials = credentials
        self.headers = {'Authorization':'Basic {}'.format(base64.b64encode(self.credentials.ghdbtoken.encode("utf-8")).decode('utf-8'))}
        self.DB = DB

    def getDB(self,DB,raw=False):
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, DB)
        print (url)
        response = requests.get( url, headers = self.headers, proxies = self.credentials.getProxyDict())
        if response.status_code == 200:
            if raw:
                return response.json()
            else:
                return base64.b64decode(response.json()['content']).decode('utf-8')
        else:
            {"connection_error": response.status_code, "message": response.text}

    def setDB(self,DB,value,sha=None):
        #raw_value = self.getKey(key,raw=True)
        #print ("RAW", raw_value)
        content = base64.b64encode(json.dumps(value).encode("utf-8")).decode('utf-8')
        if not sha:
            sha = hashlib.sha1(content.encode("utf-8")).hexdigest()
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, DB)
        payload = json.dumps({
            "message": "Creating DB: {}".format(DB),
            "content": content,
            "sha": sha
        })
        response = requests.put( url, headers = self.headers, proxies = self.credentials.getProxyDict(), data=payload)
        print (response.status_code,response.json())
    
    def delDB(self,DB,sha=None):
        if not sha:
            raw_value = self.getDB(DB)
            sha = raw_value['sha']
        payload = json.dumps({
            "message": "Deleting DB: {}".format(DB),
            "sha": sha
        })
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, DB)
        response = requests.delete( url, headers = self.headers, proxies = self.credentials.getProxyDict(), data=payload)
        print (response.status_code,response.json())

    def getKey(self,key):
        DB_content = json.loads(self.getDB(self.DB))
        if key in DB_content:
            return DB_content[key]
        else:
            return {}

    def setKey(self,key,value):
        raw_DB_content = self.getDB(self.DB,raw=True)
        DB_sha = raw_DB_content["sha"]
        DB_content = json.loads(base64.b64decode(raw_DB_content["content"]).decode('utf-8'))
        DB_content[key] = value
        self.setDB(self.DB,DB_content,sha=DB_sha)

    def delKey(self,key):
        raw_DB_content = self.getDB(self.DB,raw=True)
        DB_sha = raw_DB_content["sha"]
        DB_content = json.loads(base64.b64decode(raw_DB_content["content"]).decode('utf-8'))
        DB_content.pop(key, None)
        self.setDB(self.DB,DB_content,sha=DB_sha)

class service_github(object):
    repo = 'googis_public_layers'
    username = 'googis'
    storage = 'public_metadata'
    api_url = 'https://api.github.com'

    def __init__(self,credentials):
        '''
        The class is a convenience wrapper to google drive python module
        :param credentials:
        '''
        self.credentials = credentials
        self.headers = {'Authorization':'Basic {}'.format(base64.b64encode(self.credentials.ghdbtoken.encode("utf-8")).decode('utf-8'))}

    def getKey(self,key,sha=False):
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, key)
        print (url)
        response = requests.get( url, headers = self.headers, proxies = self.credentials.getProxyDict())
        print (response.json())
        if response.status_code == 200:
            if sha:
                return response.json()['sha']
            else:
                return base64.b64decode(response.json()['content']).decode('utf-8')

    def setKey(self,key,value):
        #sha = self.getKey(key,sha=True)
        #if not sha:
        content = base64.b64encode(json.dumps(value).encode("utf-8")).decode('utf-8')
        sha = hashlib.sha1(content.encode("utf-8")).hexdigest()
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, key)
        payload = json.dumps({
            "message": "Creating key: {}".format(key),
            "content": content,
            "sha": sha
        })
        response = requests.put( url, headers = self.headers, proxies = self.credentials.getProxyDict(), data=payload)
        print (response.status_code,response.json())
    
    def delKey(self,key):
        sha = self.getKey(key,sha=True)
        payload = json.dumps({
            "message": "Deleting key: {}".format(key),
            "sha": sha
        })
        url = "{}/repos/{}/{}/contents/data/{}.json".format(self.api_url, self.username, self.repo, key)
        response = requests.delete( url, headers = self.headers, proxies = self.credentials.getProxyDict(), data=payload)
        print (response.status_code,response.json())
    
    def listKeys(self):
        url = "{}/repos/{}/{}/contents/data/".format(self.api_url, self.username, self.repo)
        response = requests.get( url, headers = self.headers, proxies = self.credentials.getProxyDict())
        if response.status_code == 200:
            return response.json()
        else:
            print("Error listing keys",response.status_code,response.text)


class service_drive(object):

    def __init__(self,credentials):
        '''
        The class is a convenience wrapper to google drive python module
        :param credentials:
        '''
        self.credentials = credentials
        #self.configure_service()
        authorized_http = self.credentials.authorize()
        self.service = discovery.build('drive', 'v3', http=authorized_http)
        self.googis_folder = None
        self.ghdb = service_github(self.credentials)

    def configure_service(self):
        '''
        the procedure calls api discovery method and store the drive object
        :return: None
        '''
        authorized_http = self.credentials.authorize()
        if authorized_http:
            self.service = discovery.build('drive', 'v3', http=authorized_http)
        else:
            self.service = None

    def getFileMetadata(self, fileId, cacheQuery = True):
        '''
        the method returns the metadata for a  specified file id
        the metadata fields are the following:
        name, mimeType, id, description, shared, trashed, version, modifiedTime, createdTime, permissions, size, capabilities, owners
        specified in the required_fields variable
        :param fileId:
        :param cacheQuery:
        :return: file metadata
        '''
        required_fields = "name, mimeType, id, description, shared, trashed, version, modifiedTime, createdTime, permissions, size, capabilities, owners, parents"

        if cacheQuery and hasattr(self, 'lastQuery') and self.lastQuery['id'] == fileId and self.lastQuery['type'] == 'getFileInfo':
            return self.lastQuery['metadata']
        else:
            metadata = self.service.files().get(fileId=fileId, fields=required_fields).execute()
            self.lastQuery = {
                'id': fileId,
                'type': 'getFileInfo',
                'metadata': metadata
            }
            return metadata

    def isFileShared(self,fileId):
        return 'shared' in self.getFileMetadata(fileId).keys() and self.getFileMetadata(fileId)['shared']

    def isFileTrashed(self,fileId):
        return 'trashed' in self.getFileMetadata(fileId).keys() and self.getFileMetadata(fileId)['trashed']

    def isGooGisSheet(self,fileId):
        return 'description' in self.getFileMetadata(fileId).keys() and 'GOOGIS' in self.getFileMetadata(fileId)['description'].upper()

    def renew_connection(self):
        '''
        when connection stay alive too long we have to rebuild service
        '''
        try:
            self.list_files()
        except:
            # fix_print_with_import
            print("renew authorization")
            self.configure_service()

    def list_files(self, mimeTypeFilter = 'application/vnd.google-apps.spreadsheet', shared=None, anyone=None, test=None, orderBy='modifiedTime desc', filename=None):
        '''
        A method to list GooGIS application files in client_id drive specifying sorting
        :param mimeTypeFilter: default to 'application/vnd.google-apps.spreadsheet'
        :param shared: if true returns only files explicitly shared with other users
        :param anyone: if true returns shared and public files (anyone can read or write)
        :param orderBy: default to 'modifiedTime desc'
        :return: a dict (files, properties) containing the files found
        '''
        if test:
            sharedWith = " and '' in readers"
        elif shared:
            sharedWith = " and sharedWithMe = true and not 'anyone' in readers and not 'anyone' in writers "
        elif anyone:
            sharedWith = " and not '%s' in owners" % (self.credentials.client_id) #, self.credentials.client_id, self.credentials.client_id)
        else:
            sharedWith = ''
        if filename:
            app_query = " and name = '%s'" % filename
        else:
            app_query = " and trashed = false and appProperties has { key='isGOOGISsheet' and value='OK' }"
        query = "mimeType = '%s'%s%s" % (mimeTypeFilter, app_query, sharedWith)
        raw_list = self.service.files().list(orderBy=orderBy, q=query, fields='files').execute()
        #print "raw_list", raw_list
        clean_dict = collections.OrderedDict()
        order = 1
        for item in raw_list['files']:
            if item['name'] in clean_dict.keys():
                key = "%s (%s)" % (item['name'], order)
                order += 1
            else:
                key = item['name']
            clean_dict[key] = item
        return clean_dict

    def remove_permission(self, spreadsheet_id, permission_id):
        '''
        Method to remove the permission_id from the specified spreadsheet_id
        :param spreadsheet_id:
        :param permission_id:
        :return: None
        '''
        logger( "Removed permission: " + json.dumps(self.service.permissions().delete(fileId=spreadsheet_id, permissionId=permission_id).execute()))

    def publish_to_web(self, metadata):
        # fix_print_with_import
        spreadsheet_id = metadata["id"]
        print(self.add_permission(spreadsheet_id, "anyoneWithLink","reader"))
        print(self.service.revisions().update(fileId=spreadsheet_id, revisionId='head',
                                        body={'published': True, 'publishAuto': True, "publishedOutsideDomain": True,}).execute())

    def unpublish_to_web(self,metadata):
        # fix_print_with_import
        spreadsheet_id = metadata["id"]
        print(self.service.permissions().delete(fileId=spreadsheet_id, permissionId='anyoneWithLink'))
        print(self.service.revisions().update(fileId=spreadsheet_id, revisionId='head',
                                        body={'published': False, 'publishAuto': False, "publishedOutsideDomain": False,}).execute())

    def add_permission(self, spreadsheet_id, user_id, role, type = 'user'):
        '''
        Method to add a "role" permission to the specified user_id (could be 'anyone')
        :param spreadsheet_id:
        :param user_id:
        :param role: "writer" or "reader"
        :param type: default to 'user' (domain or group types are not supported at the moment)
        :return:
        '''
        if user_id == 'anyone':
            create_perm_body = {
              "kind": "drive#permission",
              "type": 'anyone',
              "role": role,
              "allowFileDiscovery": True,
            }
        elif user_id == 'anyoneWithLink':
            create_perm_body = {
              "kind": "drive#permission",
              "type": 'anyone',
              "role": role,
              "allowFileDiscovery": False,
            }
        else:
            create_perm_body = {
              "kind": "drive#permission",
              "type": type,
              "emailAddress": user_id,
              "role": role,
            }
        logger("created permission: " + json.dumps(self.service.permissions().create(fileId=spreadsheet_id, body=create_perm_body, sendNotificationEmail=None).execute()))

    def mark_as_GooGIS_sheet(self,fileId):
        if not self.googis_folder:
            self.googis_folder = self.get_googis_folder_id()
        update_body = {
          "appProperties": {
            "isGOOGISsheet": "OK"
          }
        }
        result = self.service.files().update(fileId=fileId, body=update_body).execute()
        return result

    def update_file_metadata(self,fileId,metadata):
        
        appProperties = {}
        for item in metadata:
            if not (item[0] in ('gdrive_id', 'fields', 'proj4_def')):
                appProperties[item[0]] =  item[1][:116] #pack(item[1])
        update_body = {
          "appProperties": appProperties
        }
        #print ("appProperties",update_body)
        result = self.service.files().update(fileId=fileId, body=update_body).execute()
        print (result)
        return result

    def mark_as_dirty(self,fileId):
        update_body = {
          "appProperties": {
            "dirty": "YES"
          }
        }
        result = self.service.files().update(fileId=fileId, body=update_body).execute()
        return result

    def mark_as_cleaned(self,fileId):
        update_body = {
          "appProperties": {
            "dirty": "NO"
          }
        }
        result = self.service.files().update(fileId=fileId, body=update_body).execute()
        return result

    def set_googis_folder(self, fileId):
        googis_folder = self.get_googis_folder_id()
        update_body = {
          "addParents": googis_folder
        }
        result = self.service.files().update(fileId=fileId, addParents=googis_folder).execute()
        # fix_print_with_import
        print("set_googis_folder",result)
        return result


    def get_googis_folder_id(self):
        search = self.service.files().list(q="mimeType = 'application/vnd.google-apps.folder' and name = 'GOOGIS'").execute()
        if search["files"]:
            return search["files"][0]['id']
        else:
            create_body = {
                'name': 'GOOGIS',
                'mimeType': 'application/vnd.google-apps.folder'
            }
            result = self.service.files().create(body=create_body).execute()
            return result['id']

    def download_file(self,fileId):
        '''
        returns files giving file_id
        :param fileId:
        :return: media_object
        '''
        media_obj = self.service.files().export(fileId=fileId, mimeType='text/csv').execute()
        return media_obj

    def download_sheet(self,fileId):
        '''
        :param fileId:
        :return: a csv reader object
        '''
        csv_txt = self.download_file(fileId)
        #print csv_txt
        csv_file = io.StringIO(csv_txt)
        csv_obj = csv.reader(csv_file,delimiter=',', quotechar='"')
        #print csv_obj
        return csv_obj
    
    def file_property(self, fileId, property):
        '''
        Method to return a fileId specified metadata property
        :param fileId:
        :param property:
        :return: the specified property object
        '''
        metadata = self.service.files().get(fileId=fileId,fields=property).execute()
        return metadata[property]

    def set_file_property(self,fileId, property, value):
        '''
        method to set a fileId specified property
        :param fileId:
        :param property:
        :param value:
        :return: response object
        '''
        update_body = {
            property: value
        }
        result = self.service.files().update(fileId=fileId, body=update_body).execute()
        return result

    def upload_csv_as_sheet(self, sheetName='GooGIS', body = {}, csv_file_obj = None, csv_path = None, update_sheetId = None):
        '''
        Method to upload to Google drive a csv file (or a path to a csv file) as a google-apps.spreadsheet
        :param sheetName:
        :param body:
        :param csv_file_obj:
        :param csv_path:
        :param update_sheetId:
        :return: response object
        '''
        body['mimeType'] = 'application/vnd.google-apps.spreadsheet'

        if csv_path or csv_file_obj:
            if csv_path:
                media_body = MediaFileUpload(csv_path, mimetype='text/csv', resumable=None)
            elif csv_file_obj:
                media_body = MediaIoBaseUpload(csv_file_obj, mimetype='text/csv', resumable=None)
            if update_sheetId:
                return self.service.files().update(fileId=update_sheetId, media_body=media_body).execute()
            else:
                body['description'] = 'GooGIS sheet'
                body['name'] = sheetName
                return self.service.files().create(body=body, media_body=media_body).execute()
        else:
            return None

    def upload_image(self, filePath):
        googis_folder = self.get_googis_folder_id()
        # fix_print_with_import
        print("GOOGIS folder", googis_folder)
        body = {
            'name': os.path.basename(filePath),
            'parents':[googis_folder]
        }
        media = MediaFileUpload(filePath, mimetype='image/png', resumable=None)
        if media:
            res = self.service.files().create(body=body, media_body=media).execute()
            # fix_print_with_import
            print(res)
            return res
        else:
            return None

    def trash_file(self, fileId):
        '''
        Method to move the fileId to trash
        :param fileId:
        :return:
        '''
        self.set_file_property(fileId, 'trashed', True)

    def delete_file(self, fileId):
        '''
        Method to delete the fileId
        :param fileId:
        :return:
        '''
        self.service.files().delete(fileId=fileId).execute()

    def publish_file(self, fileId, published):
        '''

        :param fileId: drive file id
        :param published: boolean True for published None for unpublished
        :return:
        '''
        revs = self.service.revisions().list(fileId=fileId).execute()["revisions"]
        update_body = {
            'published': published,
            'publishAuto': published,
            "keepForever": None,
            "publishedOutsideDomain": published
        }
        return self.service.revisions().update(fileId=fileId, revisionId=revs[-1]['id'], body=update_body).execute()


class service_spreadsheet(object):

    def __init__(self, credentials, spreadsheetId = None, new_sheet_name=None, new_sheet_data=None):
        '''
        The class is a convenience wrapper to google spreadsheets python module
        providing new_sheet_name and new_sheet_data a new spreadsheet is created and populated with data
        providing spreadsheet_id the existing data is downloaded from google sheets
        :param credentials:
        :param spreadsheetId:
        :param new_sheet_name:
        :param new_sheet_data:
        '''
        self.credentials = credentials
        self.get_service()
        self.drive = service_drive(credentials)
        if spreadsheetId:
            self.name = self.drive.file_property(spreadsheetId, 'name') #the name is used for the first child sheet
            self.spreadsheetId = spreadsheetId
        elif new_sheet_name and new_sheet_data:
            create_body ={
                "properties": {
                    "title": new_sheet_name,
                    "locale": "en"
                },
            "sheets": [
                {
                    "properties": {
                        "title": new_sheet_name,
                    },
                }
            ]
            }
            result = self.service.spreadsheets().create(body=create_body).execute()
            self.spreadsheetId = result["spreadsheetId"]
            self.name = new_sheet_name
            update_range = new_sheet_name+"!A1"
            update_body = {
                "range": update_range,
                "values": new_sheet_data,
            }
            print(self.spreadsheetId,update_range,new_sheet_data[:10])
            result = self.service.spreadsheets().values().update(spreadsheetId=self.spreadsheetId,
                                                                 range=update_range,
                                                                 body=update_body,
                                                                 valueInputOption='USER_ENTERED').execute()
            self.drive.set_googis_folder(self.spreadsheetId)
        else:
            raise Exception("service_sheet error: no sheet parameters provided")
            return

        capabilities = self.drive.file_property(self.spreadsheetId,"capabilities")
        self.update_header()
        self.canEdit = capabilities['canEdit']
        if self.canEdit:
            self.add_sheet('settings', hidden=False)
            self.add_sheet('changes_log', hidden=False)
            self.subscription = self.subscribe()
            self.drive.set_file_property(self.spreadsheetId, "description", 'GooGIS layer')
            self.drive.mark_as_GooGIS_sheet(self.spreadsheetId)
        else:
            self.changes_log_rows = self.get_line("COLUMNS",'A',sheet="changes_log")

    def get_service(self):
        '''
        the procedure calls api discovery method and store the speadsheets object
        '''
        discoveryUrl = ('https://sheets.googleapis.com/$discovery/rest?version=v4')
        self.service = discovery.build('sheets', 'v4', http=self.credentials.authorize(), discoveryServiceUrl=discoveryUrl)

    def getSpreadsheetId(self):
        '''
        method to get current spreadsheet id
        :return:
        '''
        return self.spreadsheetId

    def subscribe(self):
        '''
        method to subscribe for changes to the class object spreadsheet
        a new sheet named as client_id if created in the spreadsheet
        with the porpuse of keep memory of concurrent edits made by other users
        for subsequent syncronizations
        :return: returns subscription sheet id
        '''
        current_sheets = self.get_sheets()
        if not self.credentials.client_id in current_sheets:
            subscription = self.add_sheet(self.credentials.client_id, hidden=False)
            # fix_print_with_import
            print("subscription",subscription)
            return subscription
        else:
            # fix_print_with_import
            print("error multiple session on the same sheet!")
            self.erase_cells(self.credentials.client_id)
            return current_sheets[self.credentials.client_id]

    def unsubscribe(self):
        '''
        method to unsubscribe for changes from class object spreadsheet
        the client_id sheet is removed
        :return: response object
        '''
        try:
            update_body ={
                "requests":{
                    "deleteSheet":{
                        "sheetId": self.subscription,
                    }
                }
            }
        except:
            return None
        result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=update_body).execute()
        # fix_print_with_import
        print('UNSUBSCRIBE RESULT',result)
        return result

    def advertise(self,changes):
        '''
        method to advertise to all subscribed users the performed changes
        :param changes: a list of edits references
        :return: None
        '''
        for sheet_name,sheet_id in self.get_sheets().items():
            if not sheet_name in (self.name,'settings','summary',self.credentials.client_id):
                logger ('advertise '+ sheet_name)
                append_body = {
                    "range": sheet_name+"!A:A",
                    "majorDimension":'COLUMNS',
                    "values": [changes]
                }
                result = self.service.spreadsheets().values().append(spreadsheetId=self.spreadsheetId,
                                                                     range=sheet_name+"!A:A",
                                                                     body=append_body,
                                                                     valueInputOption='USER_ENTERED').execute()


    def update_header(self):
        '''
        Method to sync the class header dict the main spreadsheet sheet headers
        :return: None
        '''
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId, ranges=self.name+'!1:1').execute()
        #print "service_sheet",result
        self.header_map = {}
        self.header = []
        for i, value in enumerate(result['valueRanges'][0]['values'][0]):
            self.header_map[value] = int_to_a1(i+1)
            self.header.append(value)
    
    def get_sheets(self):
        '''
        method to get class object spreadsheets child sheets
        :return: list of sheets
        '''
        result = {}
        metadata = self.service.spreadsheets().get(spreadsheetId=self.spreadsheetId).execute()
        for sheet in  metadata['sheets']:
            result[sheet['properties']['title']] = sheet['properties']['sheetId']
        return result

    def toggle_sheet(self, sheet_name, sheet_id, hidden=True):
        '''
        method to hide/view spreadsheets child sheets
        :return: list of sheets
        '''

        request_body = {
            'requests': {
                'updateSheetProperties': {
                    "properties":{
                        "sheetId": sheet_id,
                        "title": sheet_name,
                        "hidden": True,
                    },
                    "fields": 'hidden'
                }
            }
        }
        result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=request_body).execute()
        return result

    def getHeader(self):
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId, ranges="summary!A1:B9", valueRenderOption='UNFORMATTED_VALUE').execute()
        return result

    def cell(self,field,row, sheet = None):
        '''
        Return a single cell value
        :param field: name of the field
        :param row: sheet row of the feature
        :param sheet: sheet name, default main table
        :return:
        '''
        if not sheet:
            sheet = self.name
        if field in self.header_map.keys():
            A1_coords = sheet+'!'+self.header_map[field]+str(row)
            return self.sheet_cell(A1_coords)
        
    def sheet_cell(self,A1_coords):
        '''
        the method returns unformatted cell value giving a cell in a1 notation
        :param A1_coords:
        :return: unformatted cell value
        '''
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId, ranges=A1_coords, valueRenderOption='UNFORMATTED_VALUE').execute()
        try:
            cell_value = result['valueRanges'][0]['values'][0][0]
        except:
            cell_value = '()'
        if cell_value == '()':
            cell_value = None
        return cell_value
        
    def set_cell(self, field, row, value, sheet = None):
        '''
        method to set a cell value giving the field name and the row
        :param field:
        :param row:
        :param value:
        :param sheet: sheet name, default main table
        :return: response object
        '''
        if not sheet:
            sheet = self.name
        if field in self.header_map.keys():
            A1_coords = sheet+'!'+self.header_map[field]+str(row)
            result = self.set_sheet_cell(A1_coords,value)
            if row == 1: #if row 1 is header so update stored header list
                self.update_header()
            return result
        else:
            #raise Exception("field %s not found") % field
            pass

    def multicell(self,lookup_ranges, sheet=None):
        if not sheet:
            sheet = self.name
        ranges = []
        for (field, row) in lookup_ranges:
            ranges.append(sheet + '!B' + str(row))
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId,
                                                                  ranges=ranges).execute()
        return result

    def set_protected_multicell(self, mods, lockBy = None):
        if not lockBy:
            lockBy = self.credentials.client_id

        mods_by_row = {}
        status_check = []
        for mod in mods:
            mods_by_row[mod[1]] = mod
            status_check.append(("STATUS", mod[1]))
        status_control = self.multicell(status_check)

        if "valueRanges" in status_control:
            for valueRange in status_control["valueRanges"]:
                if not valueRange["values"][0][0] in ('()', None, lockBy):  # check for locked row
                    row = valueRange["range"].split('B')[-1]
                    # fix_print_with_import
                    print("LOCKED ROW:", int(row))
                    # fix_print_with_import
                    print("EXPUNGE", int(row), mods_by_row.pop(int(row), None))

        if mods_by_row.values():
            value_mods_result = self.set_multicell(mods_by_row.values())
            return value_mods_result

    def set_multicell(self, mods, A1notation=None, sheet=None):
        '''
        method to set multiple cells providing a mods list
        if a client_id is provided the status field if locked by client_id to prevent concurrent edits
        :param mods: (field/rows/value) list
        :return:
        '''
        locked = None
        if not sheet:
            sheet = self.name
        update_body = {
            "valueInputOption": 'USER_ENTERED',
            "data": []
        }
        for (field, row, value) in mods:
            if A1notation or field in self.header_map.keys():
                if not value or value == NULL:
                    cleared_value = "()"
                else:
                    cleared_value = value
                if A1notation:
                    rangedef = field #if A1notation selector is True field contains the complete a1 range
                else:
                    rangedef = sheet+"!"+self.header_map[field] + str(row)
                valueRange = {
                    "range": rangedef,
                    "values": [[cleared_value]]
                }
                update_body['data'].append(valueRange)
            else:
                continue
        result = self.service.spreadsheets().values().batchUpdate(spreadsheetId=self.spreadsheetId, body=update_body).execute()
        #print result
        return result

    def get_line(self, majorDimension, line, sheet = None):
        '''
        method to get a line (a row or a column) giving a line reference
        :param majorDimension: ('ROWS' or 'COLUMNS')
        :param line: a number for row of letters for column
        :param sheet: default to None means main data sheet
        :return:
        '''
        if not sheet:
            sheet = self.name
        ranges = "%s!%s:%s" % (sheet, line, line)
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId,
                                                               ranges=ranges,
                                                               majorDimension=majorDimension,
                                                               valueRenderOption='UNFORMATTED_VALUE').execute()
        if not 'values' in result['valueRanges'][0]:
            return [] #if cells required are void return a void list
        line_values = []
        for value in result['valueRanges'][0]['values'][0]:
            if value == "()":
                line_values.append(None)
            else:
                line_values.append(value)
        return line_values

    def get_sheet_values(self, child_sheet = None):
        if not child_sheet:
            child_sheet = self.name
        ranges = child_sheet
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId,
                                                               ranges=ranges,
                                                               majorDimension="ROWS",
                                                               valueRenderOption='UNFORMATTED_VALUE').execute()
        if not 'values' in result['valueRanges'][0]:
            return [] #if cells required are void return a void list
        array_values = []
        for row in result['valueRanges'][0]['values']:
            line_values = []
            for value in row:
                if value == "()":
                    line_values.append(None)
                else:
                    line_values.append(value)
            array_values.append(line_values)
        return array_values


    def update_cells(self,a1_origin,values,dimension='ROWS'):
        '''
        method to update multiple cells starting from a1_origin position
        :param a1_origin: starting position in a1 notation
        :param values: values list
        :param dimension: "ROWS" (default) OR "COLUMNS"
        :return: response object
        '''
        update_body = {
            "valueInputOption": 'USER_ENTERED',
            "data": [{
                "range": a1_origin,
                "majorDimension": dimension,
                "values": [values],
            }]
        }
        return self.service.spreadsheets().values().batchUpdate(spreadsheetId=self.spreadsheetId, body=update_body).execute()
        
    def set_sheet_cell(self,A1_coords, value):
        '''
        set a user entered cell value giving the a1 notation sheet coordinates
        :param A1_coords: a1 notation string coordinate
        :param value: user entered value to be set
        :return: response object
        '''
        if not value or value == NULL:
            value = "()"
        body = {
            "range": A1_coords,
            "values": [[value,],],
        }

        return self.service.spreadsheets().values().update(spreadsheetId=self.spreadsheetId,
                                                           range=A1_coords,
                                                           body=body,
                                                           valueInputOption='USER_ENTERED').execute()

    def set_crs(self,crs):
        '''
        method to set layer crs in the dedicated setting sheet slot
        :param crs:
        :return: None
        '''
        self.set_sheet_cell("settings!A2",crs)

    def crs(self):
        '''
        method to get current layer crs from the dedicated setting sheet slot
        :return: crs
        '''
        return self.sheet_cell("settings!A2")

    def abstract(self):
        '''
        method to get abstract metadata
        :return abstract
        '''
        return self.sheet_cell("summary!B6")

    def setAbstract(self,abstract):
        '''
        method to set abstract metadata from layer abstract
        :param abstract:
        :return: None
        '''
        return self.set_sheet_cell("summary!B6",set_sheet_cell)

    def set_geom_type(self,crs):
        '''
        method to set layer geometry type in the dedicated setting sheet slot
        :param geometry type wkb string:
        :return: None
        '''
        self.set_sheet_cell("settings!B2",crs)

    def geom_type(self):
        '''
        method to get current layer geometry type from the dedicated setting sheet slot
        :return: geometry type wkb string
        '''
        return self.sheet_cell("settings!B2")

    def set_style_qgis(self, xmlstyle):
        '''
        method to set layer qgis style in the dedicated encoded setting sheet slot
        :param qgis layer xml text:
        :return: None
        '''
        self.pack_in_cell(xmlstyle,"settings!A3")

    def set_style_sld(self, sldstyle):
        '''
        for further uses...
        method to set layer sld style in the dedicated encoded setting sheet slot
        :param sld xml text:
        :return: None
        '''
        self.pack_in_cell(sldstyle,"settings!A4")

    def set_style_mapbox(self, mapboxstyle):
        '''
        for further uses...
        method to set layer mapbox style in the dedicated encoded setting sheet slot
        :param sld xml text:
        :return: None
        '''
        self.pack_in_cell(mapboxstyle,"settings!A5")

    def set_styles(self, qgisstyle, sldstyle, mapboxstyle):
        '''
        for further uses...
        method to set layer mapbox style in the dedicated encoded setting sheet slot
        :param sld xml text:
        :return: None
        '''
        self.pack_in_cell(mapboxstyle,"settings!A5")

    def pack_in_cell(self,content,cell):
        zip_encoded =  pack(content)
        self.set_sheet_cell(cell,zip_encoded)

    def style(self):
        '''
        the method returns stored xml qgis style definition
        :return:
        '''
        xmlstyle_zip = self.sheet_cell("settings!A3")
        return unpack(xmlstyle_zip)

    def update_metadata(self,fileId,metadata):

        print ("metadata",metadata)

        range = 'summary!A1:B8'
        update_body = {
            "range": range,
            "values": metadata,
        }
        self.service.spreadsheets().values().update(spreadsheetId=fileId,range=range, body=update_body, valueInputOption='USER_ENTERED').execute()

        appProperties = {}
        for item in metadata:
            if not (item[0] in ('gdrive_id', 'fields', 'proj4_def')):
                appProperties[item[0]] =  item[1][:116] #pack(item[1])
        update_body = {
          "appProperties": appProperties
        }

        result = self.drive.service.files().update(fileId=fileId, body=update_body).execute()
        return result

    def evaluate_formula(self,formula): #SHEET stay for the table layer
        '''
        the method returns a calculated formula on sheet data, requires write access
        :param formula:
        :return:
        '''
        formula = formula.replace('SHEET',self.name)
        self.set_sheet_cell("settings!C2",formula)
        return self.sheet_cell("settings!C2")
    
    def new_fid(self):
        '''
        the method returns a new fid for new feature creation
        :return:
        '''
        try:
            next_free_fid = self.evaluate_formula("=MAX('%s'!C2:C)" % self.name) +1
        except:
            next_free_fid = 2
        return next_free_fid


    def erase_cells(self,range):
        '''
        the method erase multiple cells specifying ranges
        :param range:
        :return:
        '''
        erase_body = {
            "ranges":[
                range,
            ]
        }
        return self.service.spreadsheets().values().batchClear(spreadsheetId=self.spreadsheetId, body=erase_body).execute()

    def mark_field_as_deleted(self,fieldPos):
        '''
        the method marks a field as deleted. The field (column) is not deleted, but simply hidden to user.
        :param fieldPos:
        :return:
        '''
        cleaned_header = []
        for field in self.header[2:]:
            if field[:8] != 'DELETED_':
                cleaned_header.append(field)
        #print "cleaned_header",cleaned_header
        #print fieldPos,cleaned_header[fieldPos]
        self.set_cell(cleaned_header[fieldPos],1,"DELETED_"+cleaned_header[fieldPos])
        return cleaned_header[fieldPos]

    def add_row(self,values_dict,childSheet = None):
        '''
        The method adds a new row with a field,new_value dict to the specified sheet
        :param values_dict:
        :param childSheet:
        :return:
        '''
        #reorder value_imput - not all fields could be present
        values = []
        for field in self.header:
            if field in values_dict.keys():
                values.append(values_dict[field])
            else:
                values.append('')
    
        append_body = {
            "majorDimension": "ROWS",
            "values": [values]
        }
        if childSheet:
            range = childSheet+"!A:ZZZ"
        else:
            range = self.name+"!A:ZZZ"
        return self.service.spreadsheets().values().append(spreadsheetId=self.spreadsheetId,
                                                           range=range,
                                                           body=append_body,
                                                           valueInputOption='USER_ENTERED').execute()

    def add_column(self,values,child_sheet = None,fill_with_null = None):
        '''
        the method adds a new column with the specified values to the specified sheet, eventually not affected rows can be set to null
        :param values:
        :param child_sheet:
        :param fill_with_null: if true fills all new cells with null '()' default to None
        :return: A1 notation of the column added
        '''
        if not child_sheet:
            child_sheet = self.name
        '''
        metadata = self.service.spreadsheets().get(spreadsheetId=self.sheetId).execute()
        width = None
        height = None
        for sheet in  metadata['sheets']:
            if sheet['properties']['title'] == child_sheet:
                width = sheet['properties']['gridProperties']['columnCount']
                height = sheet['properties']['gridProperties']['rowCount']
                break
        '''
        width = self.evaluate_formula("=COUNTA('%s'!1:1)" % child_sheet)

        if fill_with_null:
            for k in range(0,self.evaluate_formula("=COUNT('%s'!C:C)" % child_sheet)): #fill the column with null values
                values.append('()') #need to handle values > 1 item!
        append_body = {
            "majorDimension": "COLUMNS",
            "values": [values]
        }
        A1_new_col = int_to_a1(width+1)
        cell_range = "%s!%s1:%s" % (child_sheet,A1_new_col, A1_new_col)
        result = self.service.spreadsheets().values().append(spreadsheetId=self.spreadsheetId,
                                                             range=cell_range,
                                                             body=append_body,
                                                             valueInputOption='USER_ENTERED').execute()
        self.update_header()
        return A1_new_col

    
    def add_sheet(self, title, hidden=False, no_grid=False):
        '''
        the method adds e new child sheet to the spreadsheet
        :param title: sheet title
        :param hidden:
        :return:
        '''
        print ("ADD SHEET",title)
        #check if settings exists
        metadata = self.service.spreadsheets().get(spreadsheetId=self.spreadsheetId).execute()
        #print metadata
        check_sheet_exists = None
        for sheet in  metadata['sheets']:
            if sheet['properties']['title'] == title:
                print ("SHEET")
                check_sheet_exists = sheet['properties']['sheetId']
                break
        if check_sheet_exists:
            return check_sheet_exists
        update_body = {
            "requests": [{
                "addSheet": {
                    "properties": {
                        "title": title,
                        "hidden": hidden,
                        "gridProperties": {},
                    }
                },
            }]
        }
        if no_grid:
            update_body["requests"][0]["addSheet"]["properties"]["gridProperties"]["hideGridlines"] = True
        result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=update_body).execute()
        #print "add_child_sheet",result
        return result['replies'][0]['addSheet']['properties']['sheetId']
        
    def remove_deleted_rows(self):
        ranges = [self.name + '!B2:C']
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId,ranges=ranges).execute()
        requests_body = {
            'requests':[]
        }
        sheets = self.get_sheets()
        deleted = 0
        if 'values' in result['valueRanges'][0]:
            for row in result['valueRanges'][0]['values']:
                if row[0] == 'D':
                    requests_body['requests'].append(
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheets[self.name],
                                    "dimension": "ROWS",
                                    "startIndex": int(row[1])-1-deleted,
                                    "endIndex": int(row[1])-deleted
                                }
                            }
                        }
                    )
                    deleted += 1
            # fix_print_with_import
            print(requests_body)
            if deleted > 0:
                result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=requests_body).execute()
                # fix_print_with_import
                print(result)

    def remove_deleted_columns(self):
        ranges = [self.name + '!1:1']
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.spreadsheetId,ranges=ranges).execute()
        requests_body_main = {
            'requests':[]
        }
        requests_body_settings = {
            'requests':[]
        }
        sheets = self.get_sheets()
        deleted = 0
        if 'values' in result['valueRanges'][0]:
            # fix_print_with_import
            print("VALUES", result['valueRanges'][0]['values'][0])
            for count, column in enumerate (result['valueRanges'][0]['values'][0]):
                if column[:8] == 'DELETED_':
                    requests_body_main['requests'].append(
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheets[self.name],
                                    "dimension": "COLUMNS",
                                    "startIndex": count-deleted,
                                    "endIndex": count+1-deleted
                                }
                            }
                        }
                    )
                    requests_body_settings['requests'].append(
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": sheets['settings'],
                                    "dimension": "COLUMNS",
                                    "startIndex": count-deleted,
                                    "endIndex": count+1-deleted
                                }
                            }
                        }
                    )
                    deleted += 1
            # fix_print_with_import
            print(requests_body_main)
            # fix_print_with_import
            print(requests_body_settings)
            if deleted > 0:
                result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=requests_body_main).execute()
                # fix_print_with_import
                print(result)
                result = self.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheetId, body=requests_body_settings).execute()
                # fix_print_with_import
                print(result)
