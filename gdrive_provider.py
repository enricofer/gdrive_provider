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

from builtins import str
from builtins import zip
from builtins import object
__author__ = 'enricofer@gmail.com'
__date__ = '2017-03-24'
__copyright__ = 'Copyright 2017, Enrico Ferreguti'


from qgis.core import QgsMapLayer, QgsVectorLayer, QgsProject, QgsMessageLog, QgsNetworkAccessManager
from qgis.utils import plugins

from qgis.PyQt import  QtGui
from qgis.PyQt.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, QTimer, QUrl, QSize, Qt
from qgis.PyQt.QtWidgets import QAction, QDialog, QProgressBar, QDialogButtonBox, QListWidgetItem, QApplication, QTableWidgetItem
from qgis.PyQt.QtGui import QIcon, QPixmap, QCursor
# Initialize Qt resources from file resources.py
from . import resources_rc
# Import the code for the dialog
from .gdrive_provider_dialog import GoogleDriveProviderDialog, accountDialog, comboDialog, importFromIdDialog, internalBrowser, webMapDialog
from .gdrive_layer import progressBar, GoogleDriveLayer


import os
import sys
import json
import io
import collections
import re
from email.utils import parseaddr

from .services import google_authorization, service_drive, service_spreadsheet, service_github

try:
    from pydevd import *
except:
    None

# If modifying these scopes, delete your previously saved credentials
# at ~/.credentials/sheets.googleapis.com-python-quickstart.json
SCOPES = 'https://www.googleapis.com/auth/spreadsheets.readonly https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/spreadsheets https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'GooGIS_client_secret.json'
APPLICATION_NAME = 'GooGIS plugin'

logger = lambda msg: QgsMessageLog.logMessage(msg, 'Googe Drive Provider', 1)

class Google_Drive_Provider(object):
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        try:
            locale = QSettings().value('locale/userLocale')[0:2]
        except:
            locale = "en"
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'CSVProvider_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)

        # Create the dialog (after translation) and keep reference
        self.dlg = GoogleDriveProviderDialog()

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Google Drive Provider')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'GoogleDriveProvider')
        self.toolbar.setObjectName(u'GoogleDriveProvider')

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('CSVProvider', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """
        Create the menu entries and toolbar icons inside the QGIS GUI.
        """

        # fix_print_with_import
        print("initgui")
        icon_path = os.path.join(self.plugin_dir,'icon.png')
        self.add_action(
            icon_path,
            text=self.tr(u'Google Drive Provider '),
            callback=self.run,
            parent=self.iface.mainWindow())
        '''
        self.add_action(
            os.path.join(self.plugin_dir,'test.png'),
            text=self.tr(u'Google Drive Provider test '),
            callback=self.test_suite,
            parent=self.iface.mainWindow())
        '''
        self.dlg.setWindowIcon(QIcon(os.path.join(self.plugin_dir,'icon.png')))
        self.dlg.anyoneCanWrite.stateChanged.connect(self.anyoneCanWriteAction)
        self.dlg.anyoneCanRead.stateChanged.connect(self.anyoneCanReadAction)
        #self.dlg.updateWriteListButton.clicked.connect(self.updateReadWriteListAction)
        self.dlg.vacuumTablesButton.clicked.connect(self.vacuumTablesAction)
        #self.dlg.textEdit_sample.hide()
        #self.dlg.infoTextBox.hide()
        self.dlg.metadataTable.setRowCount(0)
        self.dlg.infobox_keymap.page().setNetworkAccessManager(QgsNetworkAccessManager.instance())
        self.dlg.updateReadListButton.clicked.connect(self.updateReadWriteListAction)
        self.dlg.updateReadListButton.setIcon(QIcon(os.path.join(self.plugin_dir,'shared.png')))
        self.dlg.accountButton.clicked.connect(self.updateAccountAction)
        self.dlg.exportToGDriveButton.clicked.connect(self.exportToGDriveAction)
        self.dlg.importByIdButton.clicked.connect(self.importByIdAction)
        self.dlg.listWidget.itemDoubleClicked.connect(self.run)
        self.dlg.refreshButton.clicked.connect(self.refresh_available)
        self.dlg.webMapLinkButton.clicked.connect(self.webMapLinkAction)
        self.dlg.button_box.button(QDialogButtonBox.Ok).setText("Load")
        self.dlg.helpButton.clicked.connect(self.helpAction)
        self.helpBrowser = internalBrowser("https://enricofer.github.io/gdrive_provider", 'GooGIS help')
        orderByDict = collections.OrderedDict([
            ("order by modified time; descending", "modifiedTime desc"),
            ("order by modified time; ascending", "modifiedTime"),
            ("order by name; ascending", 'name'),
            ("order by name; descending", 'name desc'),
        ])
        for txt,data in list(orderByDict.items()):
            self.dlg.orderByCombo.addItem(txt,data)
        
        self.dlg.orderByCombo.currentIndexChanged.connect(self.refresh_available)



        #add contextual menu
        #self.dup_to_google_drive_action = QAction(QIcon(icon_path), "Duplicate to Google drive layer", self.iface.legendInterface() )
        #self.iface.legendInterface().addLegendLayerAction(self.dup_to_google_drive_action, "","01", QgsMapLayer.VectorLayer,True)
        #self.dup_to_google_drive_action.triggered.connect(self.dup_to_google_drive)

        #add contextual menu
        self.dup_to_google_drive_action = QAction(QIcon(os.path.join(icon_path)), u"Duplicate to Google drive layer", self.iface )
        self.iface.addCustomActionForLayerType(self.dup_to_google_drive_action,"", QgsMapLayer.VectorLayer,True)
        self.dup_to_google_drive_action.triggered.connect(self.dup_to_google_drive)


        #authorize plugin
        s = QSettings()
        self.client_id = s.value("GooGIS/gdrive_account",  defaultValue =  None)
        self.myDrive = None
        #if self.client_id:
        #    self.authorization = google_authorization(SCOPES,os.path.join(self.plugin_dir,'credentials'),APPLICATION_NAME,self.client_id)
        #QgsProject.instance().layerLoaded.connect(self.loadGDriveLayers)
        QgsProject.instance().readProject.connect(self.loadGDriveLayers)
        QgsProject.instance().layersWillBeRemoved.connect(self.updateSummarySheet)

    def helpAction(self):
        self.helpBrowser.setWindowFlags(Qt.WindowSystemMenuHint | Qt.WindowTitleHint) 
        self.helpBrowser.setMinimumSize(QSize(900, 600))
        self.helpBrowser.show()
        self.helpBrowser.raise_()

    def unload(self):
        """
        Removes the plugin menu item and icon from QGIS GUI.
        """
        try:
            self.remove_GooGIS_layers()
        except:
            pass
        QgsProject.instance().readProject.disconnect(self.loadGDriveLayers)
        QgsProject.instance().layersWillBeRemoved.disconnect(self.updateSummarySheet)
        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr(u'&Google Drive Provider'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar
        self.iface.removeCustomActionForLayerType(self.dup_to_google_drive_action)

    def GooGISLayers(self):
        '''
        iterator over QGIS layer associated to plugin
        :return:
        '''
        for layer in list(QgsProject.instance().mapLayers().values()):
            if self.isGooGISLayer(layer):
                yield layer

    def isGooGISLayer(self, layer):
        '''
        Method to check if a QGIS layer is associated to plugin
        :param layer:
        :return: True or False
        '''
        if layer.type() != QgsMapLayer.VectorLayer:
            return
        use = layer.customProperty("googleDriveId", defaultValue=None)
        return use # not (use == None)

    def loadGDriveLayers(self,dom):
        '''
        Landing method for readProject signal. Loads layer data from google drive with "googleDriveId" custom property
        :param dom:
        '''
        for layer in self.GooGISLayers():
            google_id = layer.customProperty("googleDriveId", defaultValue=None)
            if google_id:
                if not self.client_id or not self.myDrive:
                    self.updateAccountAction()
                self.gdrive_layer = GoogleDriveLayer(self, self.authorization, layer.name(), spreadsheet_id=google_id, loading_layer=layer)
                # fix_print_with_import
                print("reading", google_id, layer.id(), self.gdrive_layer.lyr.id())
                #glayer.makeConnections(layer)
                layer.editingStarted.connect(self.gdrive_layer.editing_started)
                layer.updateExtents()

    def updateSummarySheet(self,layer_ids):
        for layer_id in layer_ids:
            removing_layer = QgsProject.instance().mapLayer(layer_id)
            if self.isGooGISLayer(removing_layer):
                self.myDrive.renew_connection()
                removing_layer.gDriveInterface.update_summary_sheet()

    def test_suite(self):
        if not self.client_id or not self.myDrive:
            self.updateAccountAction()
        #self.sheet_layer = GoogleDriveLayer(self.authorization, sheet_name, sheet_id='1hC8iT7IutoYDVDLlEWF8_op2viNRsUdv8tTVo9RlPkE')
        #gdrive = service_drive(self.authorization)
        #gsheet = service_sheet(self.authorization,'1hC8iT7IutoYDVDLlEWF8_op2viNRsUdv8tTVo9RlPkE')
        self.myDrive.configure_service()
        layer_a = QgsVectorLayer(os.path.join(self.plugin_dir,'test','dataset','c0601016_SistemiEcorelazionali.shp'), "layer_a", 'ogr')
        layer_b = QgsVectorLayer(os.path.join(self.plugin_dir,'test','dataset','c0601037_SpecieArboree.shp'), "layer_b", 'ogr')
        layer_c = QgsVectorLayer(os.path.join(self.plugin_dir,'test','dataset','c0509028_LocSitiContaminati.shp'), "layer_c", 'ogr')
        lv = plugins['layerVersion']
        for layer in  (layer_a, layer_b, layer_c ):
            # fix_print_with_import
            print("LAYER", layer.name())
            glayer = GoogleDriveLayer(self, self.authorization, layer.name(), importing_layer=layer, test=True)
            gsheet = glayer.get_service_sheet()
            glayer.lyr.startEditing()
            if not layer: #layer_a:
                for s in ['1','2','3']:
                    qlv_path = os.path.join(self.plugin_dir,'test','dataset',layer.name()+s+'.qlv')
                    # fix_print_with_import
                    print("qlv_path "+s, qlv_path)
                    lv.editingStateLoader.setEditsXMLDefinition(qlv_path, batch=True)
                    if s == '3':
                        glayer.lyr.rollBack()
                    else:
                        glayer.lyr.commitChanges()
            else:
                qlv_path = os.path.join(self.plugin_dir,'test','dataset',layer.name()+'.qlv')
                # fix_print_with_import
                print("qlv_path", qlv_path)
                lv.editingStateLoader.setEditsXMLDefinition(qlv_path, batch=True)
                glayer.lyr.commitChanges()

            # fix_print_with_import
            print("T1", gsheet.cell('Shape_Area',25))
            # fix_print_with_import
            print("T2", gsheet.set_cell('Shape_Area',24,234.500))
            # fix_print_with_import
            print("T3", gsheet.set_cell('Shape_Area',23,1000))
            # fix_print_with_import
            print("T4", gsheet.set_cell('Shape_Leng',22,'CIAOOOOO!'))
            # fix_print_with_import
            print("T5", gsheet.set_cell('Shape_Leng',21,None))
            # fix_print_with_import
            print("T6", gsheet.cell('Shape_Area',23))
            # fix_print_with_import
            print("T6", gsheet.cell('Shape_Leng',24))
            gsheet.add_sheet('byebye')
            gsheet.set_sheet_cell('byebye!A1', 'ciao')
            # fix_print_with_import
            print("FORMULA =SUM(SHEET!F2:F30):",gsheet.evaluate_formula('=SUM(SHEET!F2:F30)'))
            # fix_print_with_import
            print("FORMULA =MAX(SHEET!C2:C):",gsheet.evaluate_formula('=MAX(SHEET!C2:C)'))
            # gsheet.set_cell('barabao',33, 'ciao')
            fid = gsheet.new_fid()
            # fix_print_with_import
            print("NEW FID", fid)
            update_fieds = list(set(gsheet.header) - set(['WKTGEOMETRY','STATUS']))
            # fix_print_with_import
            print("update_fieds", update_fieds)
            # fix_print_with_import
            print("UPDATE DICT",dict(list(zip(update_fieds,["UNO",fid,34234,665.345,455.78,"HH"]))))
            # fix_print_with_import
            print("APPEND_ROW", gsheet.add_row(dict(list(zip(update_fieds,['10000',"UNO",fid,34234,665.345,455.78,"HH"])))))
            # fix_print_with_import
            print("APPEND_COLUMN", gsheet.add_column(["UNO",fid,34234,665.345,455.78,"HH"]))
            # fix_print_with_import
            print("CRS", gsheet.crs())
            # fix_print_with_import
            print("NEW_FID", gsheet.new_fid())
            # fix_print_with_import
            print("DELETED FIELD 5", gsheet.mark_field_as_deleted(5))
            # fix_print_with_import
            print(glayer.service_drive.trash_file(glayer.get_gdrive_id()))
        # fix_print_with_import
        print("TEST ENDED")

    def load_available_sheets(self):
        '''
        Method that loads from user google drive the available GooGIS layers list
        :return:
        '''
        bak_available_list_filepath = os.path.join(self.plugin_dir,'credentials','available_sheets.json')
        if os.path.exists(bak_available_list_filepath):
            with open(bak_available_list_filepath) as available_file:
                self.available_sheets = json.load(available_file)
        else:
            self.refresh_available()

    def refresh_available(self):
        '''
        Method for refreshing dialog list widget with available GooGIS layers
        '''
        self.myDrive.configure_service()
        self.available_sheets = self.myDrive.list_files(orderBy=self.dlg.orderByCombo.itemData(self.dlg.orderByCombo.currentIndex()))
        try:
            self.dlg.listWidget.currentItemChanged.disconnect(self.viewMetadata)
        except:
            pass
        self.dlg.listWidget.clear()
        self.dlg.writeListTextBox.clear()
        self.dlg.readListTextBox.clear()
        sharedIcon = QIcon(os.path.join(self.plugin_dir,'shared.png'))
        anyoneIcon = QIcon(os.path.join(self.plugin_dir,'globe.png'))
        nullIcon = QIcon(os.path.join(self.plugin_dir,'null.png'))
        for sheet_name, sheet_metadata in self.available_sheets.items():
            newItem = QListWidgetItem(QIcon(),sheet_name,self.dlg.listWidget, QListWidgetItem.UserType)
            if not sheet_metadata["capabilities"]["canEdit"]:
                font = newItem.font()
                font.setItalic(True)
                newItem.setFont(font)
            #if sheet in shared_sheets.keys():
            permissions = self.get_permissions(sheet_metadata)
            if 'anyone' in permissions:
                newItem.setIcon(anyoneIcon)
            elif permissions != {}:
                newItem.setIcon(sharedIcon)
            else:
                newItem.setIcon(nullIcon)
            #newItem.setIcon(QIcon(os.path.join(self.plugin_dir,'shared.png')))
            #newItem.setText(sheet)
            self.dlg.listWidget.addItem(newItem)
        self.dlg.listWidget.currentItemChanged.connect(self.viewMetadata)

    def get_permissions(self,metadata):
        '''
        returns a simplified list of permissions from the downloaded metadata
        :param metadata: the downloaded file metadata
        '''
        permissions = {}
        if 'permissions' in metadata:
            for permission in metadata['permissions']:
                if permission['type'] == 'anyone':
                    permissions['anyone'] = permission['role']
                if permission['type'] == 'user' and permission['emailAddress'] != self.client_id:
                    permissions[permission['emailAddress']] = permission['role']
        return permissions

    def viewMetadata(self,item,prev):
        '''
        Method for populating item details slots (metadata, thumbnail, permissions) on list widget selection
        :param item: the selcted list widget item
        :param prev: not used
        '''

        def getTableItem(content,editingDisabled=True):
            item = QTableWidgetItem(content)
            if editingDisabled:
                item.setFlags( Qt.ItemIsSelectable |  Qt.ItemIsEnabled )
            return item

        self.myDrive.renew_connection()
        self.dlg.anyoneCanRead.setChecked(False)
        self.dlg.anyoneCanWrite.setChecked(False)
        self.current_spreadsheet_id =  self.available_sheets[item.text()]['id']
        self.current_metadata = self.available_sheets[item.text()]
        ###TOO SLOW BROWSING
        #sheet_service = service_spreadsheet(self.authorization, spreadsheetId=self.current_spreadsheet_id)
        #header = sheet_service.getHeader()
        #print(header)

        page = '''
<html>
<head>
<style>
.keymap {{
    background-image: url("{}");
    -webkit-background-size: contain;
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    width: 100%;
    height: 100%;
}}
</style>
</head>
<body>
<div class="keymap"></div>
</body>
</html>
        '''

        thumbnail_rif = self.myDrive.list_files(mimeTypeFilter='image/png', filename=item.text()+'.png' )
        if thumbnail_rif:
            web_link = 'https://drive.google.com/uc?export=view&id='+ thumbnail_rif[item.text()+'.png']['id']
            # fix_print_with_import
            print("web_link",web_link)
        else:
            web_link = '_'

        self.dlg.infobox_keymap.page().currentFrame().setHtml(page.format(web_link))

        owners_list = [owner["emailAddress"] for owner in self.current_metadata['owners']]
        owners = " ".join(owners_list)

        if self.current_metadata['capabilities']['canEdit']:
            writeCapability = "editable file"
        else:
            writeCapability = "read-only file"

        #print (self.current_metadata)
        self.dlg.metadataTable.clear()
        self.dlg.metadataTable.setRowCount(0)
        for row in ['geometry_type', 'srid', 'features', 'extent', "abstract"][::-1]:
            if row in self.current_metadata["appProperties"]:
                self.dlg.metadataTable.insertRow(0)
                self.dlg.metadataTable.setItem(0,0,getTableItem(row))
                self.dlg.metadataTable.setItem(0,1,getTableItem(self.current_metadata["appProperties"][row]))
        for row in ['owner', 'name', 'id', 'modifiedTime', 'createdTime', 'version', 'capability'][::-1]:
            self.dlg.metadataTable.insertRow(0)
            self.dlg.metadataTable.setItem(0,0,getTableItem(row))
            self.dlg.metadataTable.setItem(0,1,getTableItem(dict(owner=owners, capability=writeCapability, **self.current_metadata)[row]))
        self.dlg.metadataTable.resizeColumnsToContents()
        #self.dlg.metadataTable.resizeRowsToContents()
        self.dlg.metadataTable.horizontalHeader().setStretchLastSection(True)

        # fix_print_with_import

        permission_groups = [
            self.dlg.readListGroupBox,
            self.dlg.writeListGroupBox,
        ]
        for group in permission_groups:
            if self.client_id in owners:
                group.setEnabled(True)
            else:
                group.setEnabled(False)

        self.original_write_list = []
        self.original_read_list = []
        if not 'permissions' in self.current_metadata:
            return
        for permission in self.current_metadata['permissions']:
            if permission['role'] == 'writer':
                if permission['type'] == 'anyone':
                    #self.original_write_list.append('anyone')
                    self.dlg.anyoneCanWrite.setChecked(True)
                else:
                    self.original_write_list.append(permission['emailAddress'])
            if permission['role'] == 'reader':
                if permission['type'] == 'anyone':
                    #self.original_read_list.append('anyone')
                    self.dlg.anyoneCanRead.setChecked(True)
                else:
                    self.original_read_list.append(permission['emailAddress'])

        self.dlg.writeListTextBox.clear()
        self.dlg.writeListTextBox.appendPlainText(' '.join(self.original_write_list))

        self.dlg.readListTextBox.clear()
        self.dlg.readListTextBox.appendPlainText(' '.join(self.original_read_list))

        glayer_is_loaded = None
        for glayer in self.GooGISLayers():
            print(glayer,self.isGooGISLayer(glayer),self.current_spreadsheet_id)
            if self.isGooGISLayer(glayer) == self.current_spreadsheet_id:
                glayer_is_loaded = True
                break

        if self.client_id in owners_list and not glayer_is_loaded:
            self.dlg.vacuumTablesButton.setDisabled(False)
        else:
            self.dlg.vacuumTablesButton.setDisabled(True)

    def vacuumTablesAction(self):
        self.sheet_service = service_spreadsheet(self.authorization, spreadsheetId=self.current_spreadsheet_id)
        sheets = self.sheet_service.get_sheets()
        open_activity = list(set(sheets.keys()) - set([self.sheet_service.name, self.client_id,  'settings', 'summary', 'changes_log']))
        # fix_print_with_import
        #print(self.client_id,sheets,open_activity)
        if not open_activity:
            self.remove_GooGIS_layers(layerId_to_delete=self.current_spreadsheet_id)
            self.sheet_service.remove_deleted_rows()
            self.sheet_service.remove_deleted_columns()
        else:
            # fix_print_with_import
            print("CAN'T VACUUM TABLES")

    def anyoneCanWriteAction(self,state):
        '''
        Landing method for stateChanged signal. Sincronize list box with related checkbox checking
        :param state: not used
        '''
        if self.dlg.anyoneCanWrite.isChecked():
            self.dlg.writeListTextBox.setDisabled(True)
        else:
            self.dlg.writeListTextBox.setDisabled(False)

    def anyoneCanReadAction(self,state):
        '''
        Landing method for stateChanged signal. Sincronize list box with related checkbox checking
        :param state: not used
        '''
        if self.dlg.anyoneCanRead.isChecked():
            self.dlg.readListTextBox.setDisabled(True)
        else:
            self.dlg.readListTextBox.setDisabled(False)

    def updateReadWriteListAction(self):
        '''
        Method to sincronize read write boxes with current item metadata
        '''

        try:
            current_spreadsheet_id = self.current_metadata['id']
        except:
            return

        rw_commander = collections.OrderedDict()
        rw_commander["reader"] = {
            "text_widget": self.dlg.readListTextBox,
            "check_anyone_widget": self.dlg.anyoneCanRead,
            "original_list": self.original_read_list,
            "update_publish": None
        }
        rw_commander["writer"] = {
            "text_widget": self.dlg.writeListTextBox,
            "check_anyone_widget": self.dlg.anyoneCanWrite,
            "original_list": self.original_write_list,
            "update_publish": None
        }

        for role, widgets in rw_commander.items():
            cleaned_update_list = []
            for permission in widgets['text_widget'].toPlainText().split(' '):
                if re.match("([^@|\s]+@[^@]+\.[^@|\s]+)", permission):
                    cleaned_update_list.append(permission)
            if widgets['check_anyone_widget'].isChecked():
                if not 'anyone' in cleaned_update_list:
                    cleaned_update_list.append('anyone')
            delete_from_rw_list = list(set(widgets['original_list']) - set(cleaned_update_list))
            add_to_rw_list = list(set(cleaned_update_list) - set(widgets['original_list']))
            if 'permissions' in self.current_metadata:
                for permission in self.current_metadata['permissions']:
                    if permission['role'] == role:
                        if (permission['type'] == 'anyone' and not widgets['check_anyone_widget'].isChecked()) or \
                                ('emailAddress' in permission and permission['emailAddress'] in delete_from_rw_list):
                            self.myDrive.remove_permission(current_spreadsheet_id, permission['id'])
                        if (permission['type'] == 'anyone' and not widgets['check_anyone_widget'].isChecked()):
                            widgets['update_publish'] = True
                for new_read_user in add_to_rw_list:
                    self.myDrive.add_permission(current_spreadsheet_id, new_read_user,role)
                    if new_read_user == 'anyone':
                        widgets['update_publish'] = True
        #update public link in summary sheet
        if rw_commander["reader"]['update_publish']: # or rw_commander["writer"]['update_publish']:
            publish_state = rw_commander["reader"]["check_anyone_widget"].isChecked() # or rw_commander["writer"]["check_anyone_widget"].isChecked()
            # fix_print_with_import
            print("publish_state",publish_state)
            if publish_state:
                publicLinkContent = ['public link', "https://enricofer.github.io/GooGIS2CSV/converter.html?spreadsheet_id="+current_spreadsheet_id]
                self.myDrive.publish_to_web(self.current_metadata)
                self.myDrive.ghdb.setKey(self.current_spreadsheet_id,self.current_metadata['appProperties'])
            else:
                publicLinkContent = [' ', ' ']
                self.myDrive.unpublish_to_web(self.current_metadata)
                self.myDrive.ghdb.delKey(self.current_spreadsheet_id)
            service_sheet = service_spreadsheet(self.authorization, spreadsheetId=current_spreadsheet_id)
            range = 'summary!A9:B9'
            update_body = {
                "range": range,
                "values": [publicLinkContent]
            }
            # fix_print_with_import
            print("update_public_link", service_sheet.service.spreadsheets().values().update(spreadsheetId=current_spreadsheet_id,range=range, body=update_body, valueInputOption='USER_ENTERED').execute())

            self.refresh_available()


    def updateAccountAction(self, error=None):
        """
        Method to update current google drive user
        :param error:
        """

        result = accountDialog.get_new_account(self.client_id, error=error)
        if result:
            self.authorization = google_authorization(self, SCOPES, os.path.join(self.plugin_dir, 'credentials'),
                                                      APPLICATION_NAME, result)
            # fix_print_with_import
            print("self.authorization", self.authorization)
            self.myDrive = service_drive(self.authorization)
            # fix_print_with_import
            print("self.myDrive", self.myDrive)
            if not self.myDrive:
                self.updateAccountAction(self, error=True)
            if result != self.client_id:
                self.client_id = result
                s = QSettings()
                s.setValue("GooGIS/gdrive_account", self.client_id)
                self.remove_GooGIS_layers()
                self.run()


    def exportToGDriveAction(self):
        """
        method to export a selected QGIS layer to Google drive (from dialog or layer contextual menu
        """
        layer = comboDialog.select(QgsProject.instance().mapLayers(), self.iface.activeLayer())
        self.dup_to_google_drive(layer)

    def importByIdAction(self):
        '''
        Method to import to user google drive a public sheet giving its fileId
        '''
        import_id = importFromIdDialog.getNewId()
        if import_id:
            import_id = import_id.strip()
            self.myDrive.configure_service()
            try:
                response = self.myDrive.service.files().update(fileId=import_id, addParents='root').execute()
                QApplication.processEvents()
                self.refresh_available()
            except Exception as e:
                logger("exception %s; can't open fileid %s" % (str(e),import_id))
                pass

    def remove_GooGIS_layers(self, layerId_to_delete=None):
        '''
        Method to remove loaded GooGIS layer from legend and map canvas. Used uninstalling plugin
        '''
        self.myDrive.renew_connection()
        for layer_id,layer in QgsProject.instance().mapLayers().items():
            # fix_print_with_import
            googleDriveId = layer.customProperty("googleDriveId", defaultValue=None)
            #print(layer_id, hasattr(layer, 'gDriveInterface'))
            if googleDriveId :
                if not layerId_to_delete or googleDriveId == layerId_to_delete:
                    QgsProject.instance().removeMapLayer(layer.id())

    def run(self):
        """
        show the plugin dialog
        """

        if not self.client_id or not self.myDrive:
            self.updateAccountAction()
        self.refresh_available()
        self.dlg.setWindowFlags(Qt.WindowSystemMenuHint | Qt.WindowTitleHint) 
        self.dlg.show()
        self.dlg.raise_()
        # Run the dialog event loop
        result = self.dlg.exec_()
        # See if OK was pressed
        if result and self.dlg.listWidget.selectedItems():
            self.load_sheet(self.dlg.listWidget.selectedItems()[0])

    def load_sheet(self,item):
        '''
        Method for loading as QGIS layer the selected google drive layer
        :param item:
        :return:
        '''
        sheet_name = item.text()
        sheet_id = self.available_sheets[sheet_name]['id']
        self.myDrive.configure_service()
        self.gdrive_layer = GoogleDriveLayer(self, self.authorization, sheet_name, spreadsheet_id=sheet_id)

    def dup_to_google_drive(self, layer = None):
        '''
        Method for duplicating a current QGIS layer to a Google drive sheet (AKA GooGIS layer)
        :param layer:
        :return:
        '''
        if not layer:
            layer = self.iface.activeLayer()
        if not self.client_id or not self.myDrive:
            self.updateAccountAction()           
        #try:
            #Wait cursor
        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        
        self.myDrive.configure_service()
        QApplication.processEvents()
        
        self.gdrive_layer = GoogleDriveLayer(self, self.authorization, layer.name(), importing_layer=layer)
        QApplication.processEvents()
        
        self.refresh_available()
        
        QApplication.restoreOverrideCursor()
        QApplication.processEvents()

        try:
            pass
        except Exception as e:
            # fix_print_with_import
            print("EXCEPTION", str(e))
            QApplication.restoreOverrideCursor()
            None

    def webMapLinkAction(self):
        '''
        Method to select public maps for browsing them in external webbrowser
        :return:
        '''
        # fix_print_with_import
        print(webMapDialog.get_web_link(self))