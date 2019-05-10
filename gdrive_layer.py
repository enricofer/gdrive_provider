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
from builtins import zip
from builtins import str
from builtins import range
from builtins import object
__author__ = 'enricofer@gmail.com'
__date__ = '2017-03-24'
__copyright__ = 'Copyright 2017, Enrico Ferreguti'


import csv
import shutil
import os
import io
import sys
import io
import json
import collections
import base64
import zlib
import _thread
import traceback
from time import sleep

from tempfile import NamedTemporaryFile
from qgis.PyQt import  QtGui
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtWidgets import QProgressBar, QAction, QWidget, QApplication
from qgis.PyQt.QtGui import QIcon, QPixmap
from qgis.PyQt.QtCore import QObject, pyqtSignal, QThread, QVariant, QSize, Qt

from qgis.core import (QgsVectorLayer, QgsFeature, QgsGeometry, QgsExpression, QgsField, QgsMapLayer, QgsMapRendererParallelJob,
                       QgsFeatureRequest, QgsMessageLog,QgsCoordinateReferenceSystem, Qgis, QgsReadWriteContext, QgsProject)

from qgis.gui import QgsMessageBar, QgsMapCanvas

import qgis.core

logger = lambda msg: QgsMessageLog.logMessage(msg, 'Googe Drive Provider', 1)


from .services import google_authorization, service_drive, service_spreadsheet

from mapboxgl.mapboxgl import toMapboxgl

from .utils import slugify


class progressBar(object):
    def __init__(self, parent, msg = ''):
        '''
        progressBar class instatiation method. It creates a QgsMessageBar with provided msg and a working QProgressBar
        :param parent:
        :param msg: string
        '''
        self.iface = parent.iface
        widget = self.iface.messageBar().createMessage("GooGIS plugin:",msg)
        progressBar = QProgressBar()
        progressBar.setRange(0,0) #(1,steps)
        progressBar.setValue(0)
        progressBar.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        widget.layout().addWidget(progressBar)
        QApplication.processEvents()
        self.iface.messageBar().pushWidget(widget, Qgis.Info, 50)
        QApplication.processEvents()

    def stop(self, msg = ''):
        '''
        the progressbar is stopped with a succes message
        :param msg: string
        :return:
        '''
        self.iface.messageBar().clearWidgets()
        message = self.iface.messageBar().createMessage("GooGIS plugin:",msg)
        self.iface.messageBar().pushWidget(message, Qgis.Success, 3)

class GoogleDriveLayer(QObject):
    """ Pretend we are a data provider """

    invalidEdit = pyqtSignal()
    deferredEdit = pyqtSignal()
    dirty = False
    doing_attr_update = False
    geom_types = ("Point", "LineString", "Polygon","Unknown","NoGeometry")


    def __init__(self, parent, authorization, layer_name, spreadsheet_id = None, loading_layer = None, importing_layer = None, crs_def = None, geom_type = None, test = None):
        '''
        Initialize the layer by reading the Google drive sheet, creating a memory
        layer, and adding records to it, optionally used fo layer export to google drive
        :param parent:
        :param authorization: google authorization object
        :param layer_name: the layer name
        :param spreadsheet_id: the spreadsheetId of the table to download and load as qgis layer; default to None
        :param loading_layer: the layer loading from project file; default to None
        :param importing_layer: the layer that is being imported; default to None
        :param test: used for testing
        '''

        super(GoogleDriveLayer, self).__init__()
        # Save the path to the file soe we can update it in response to edits
        self.test = test
        self.parent = parent
        self.iface = parent.iface
        bar = progressBar(self, 'loading google drive layer')
        self.service_drive = service_drive(authorization)
        self.client_id = authorization.client_id
        self.authorization = authorization
        if spreadsheet_id:
            self.spreadsheet_id = spreadsheet_id
            self.service_sheet = service_spreadsheet(authorization, self.spreadsheet_id)
        elif importing_layer:
            print("MAPBOX STYLE",self.layer_style_to_json(importing_layer))
            layer_as_list = self.qgis_layer_to_list(importing_layer)
            self.service_sheet = service_spreadsheet(authorization, new_sheet_name=importing_layer.name(), new_sheet_data = layer_as_list)
            self.spreadsheet_id = self.service_sheet.spreadsheetId
            self.service_sheet.set_crs(importing_layer.crs().authid())
            self.service_sheet.set_geom_type(self.geom_types[importing_layer.geometryType()])
            self.service_sheet.set_style_qgis(self.layer_style_to_xml(importing_layer))
            self.service_sheet.set_style_sld(self.SLD_to_xml(importing_layer))
            self.service_sheet.set_style_mapbox(self.layer_style_to_json(importing_layer))
            self.dirty = True
            self.saveFieldTypes(importing_layer.fields())

        self.reader = self.service_sheet.get_sheet_values()
        self.header = self.reader[0]

        self.crs_def = self.service_sheet.crs()
        self.geom_type = self.service_sheet.geom_type()
        logger("LOADED GOOGLE SHEET LAYER: %s CRS_ID:%s GEOM_type:%s" % (self.service_sheet.name,self.crs_def, self.geom_type))
        #logger( "GEOM_type "+ self.geom_type)
        # Build up the URI needed to create memory layer
        if loading_layer:
            self.lyr = loading_layer
            # fix_print_with_import
            print("LOADIN", self.lyr, loading_layer)
            attrIds = [i for i in range (0, self.lyr.fields().count())]
            self.lyr.dataProvider().deleteAttributes(attrIds)
            self.lyr.updateFields()
        else:
            self.uri = self.uri = "Multi%s?crs=%s&index=yes" % (self.geom_type, self.crs_def)
            #logger(self.uri)
            # Create the layer
            self.lyr = QgsVectorLayer(self.uri, layer_name, 'memory')
            self.lyr.setCustomProperty("googleDriveId", self.spreadsheet_id)
        fields_types = self.service_sheet.get_line("ROWS", 1, sheet="settings")
        attributes = []
        for i in range(2,len(self.header)):
            if self.header[i][:8] != 'DELETED_':
                type_pack = fields_types[i].split("|")
                attributes.append(QgsField(name=self.header[i],type=int(type_pack[0]), len=int(type_pack[1]), prec=int(type_pack[2])))
                #self.uri += u'&field={}:{}'.format(fld.decode('utf8'), field_name_types[fld])
        self.lyr.dataProvider().addAttributes(attributes)
        self.lyr.updateFields()

        self.xml_to_layer_style(self.lyr,self.service_sheet.style())
        self.lyr.rendererChanged.connect(self.style_changed)

        self.add_records()

        # Make connections
        self.makeConnections(self.lyr)

        # Add the layer the map
        if not loading_layer:
            QgsProject.instance().addMapLayer(self.lyr)
        else:
            pass
            #self.lyr.editingStarted.emit()
        #create summary if importing
        if importing_layer:
            self.update_summary_sheet()
        self.lyr.gdrive_control = self
        bar.stop("Layer %s succesfully loaded" % layer_name)

    def makeConnections(self,lyr):
        '''
        The method handle default signal connections to the connected qgis memory layer
        :param lyr: qgis layer
        :return:
        '''
        self.deferredEdit.connect(self.apply_locks)
        lyr.editingStarted.connect(self.editing_started)
        lyr.editingStopped.connect(self.editing_stopped)
        lyr.committedAttributesDeleted.connect(self.attributes_deleted)
        lyr.committedAttributesAdded .connect(self.attributes_added)
        lyr.committedFeaturesAdded.connect(self.features_added)
        lyr.committedGeometriesChanges.connect(self.geometry_changed)
        lyr.committedAttributeValuesChanges.connect(self.attributes_changed)
        lyr.destroyed.connect(self.unsubscribe)
        lyr.beforeCommitChanges.connect(self.inspect_changes)
        #add contextual menu
        #self.sync_with_google_drive_action = QAction(QIcon(os.path.join(self.parent.plugin_dir,'sync.png')), "Sync with Google drive", self.iface.legendInterface() )
        #self.iface.legendInterface().addLegendLayerAction(self.sync_with_google_drive_action, "","01", QgsMapLayer.VectorLayer,False)
        #self.iface.legendInterface().addLegendLayerActionForLayer(self.sync_with_google_drive_action, lyr)
        #self.sync_with_google_drive_action.triggered.connect(self.sync_with_google_drive)
        self.sync_with_google_drive_action = QAction(QIcon(os.path.join(self.parent.plugin_dir,'sync.png')), "Sync with Google drive", self.iface )
        self.iface.addCustomActionForLayer(self.sync_with_google_drive_action, lyr)
        self.sync_with_google_drive_action.triggered.connect(self.sync_with_google_drive)

        lyr.gDriveInterface = self

    def add_records(self):
        '''
        Add records to the memory layer by reading the Google Sheet
        '''
        self.lyr.startEditing()

        for i, row in enumerate(self.reader[1:]):
            flds = collections.OrderedDict(list(zip(self.header, row)))
            status = flds.pop('STATUS')

            if status != 'D': #non caricare i deleted
                wkt_geom = zlib.decompress(base64.b64decode(flds.pop('WKTGEOMETRY'))).decode("utf-8")
                #print (wkt_geom)
                #fid = int(flds.pop('FEATUREID'))
                feature = QgsFeature()
                geometry = QgsGeometry.fromWkt(wkt_geom)
                feature.setGeometry(geometry)
                cleared_row = [] #[fid]
                for field, attribute in flds.items():
                    if field[:8] != 'DELETED_': #skip deleted fields
                        if attribute == '()':
                            cleared_row.append(qgis.core.NULL)
                        else:
                            cleared_row.append(attribute)
                    else:
                        logger( "DELETED " + field)
                #print "cleared_row", cleared_row
                feature.setAttributes(cleared_row)
                self.lyr.addFeature(feature)
        self.lyr.commitChanges()

    def style_changed(self):
        '''
        landing method for rendererChanged signal. It stores xml qgis style definition to the setting sheet
        '''
        logger( "style changed")
        self.service_sheet.set_style_qgis(self.layer_style_to_xml(self.lyr))
        self.service_sheet.set_style_sld(self.SLD_to_xml(self.lyr))
        self.service_sheet.set_style_mapbox(self.layer_style_to_json(self.lyr))

    def renew_connection(self):
        '''
        when connection stay alive too long we have to rebuild service
        '''
        self.service_drive.renew_connection()

    def sync_with_google_drive(self):
        self.renew_connection()
        self.update_from_subscription()
        self.update_summary_sheet()

    def update_from_subscription(self):
        '''
        The method updates qgis memory layer with changes made by other users and sincronize the local qgis layer with google sheet spreadsheet
        '''
        self.renew_connection()
        bar = progressBar(self, 'updating local layer from remote')
        # fix_print_with_import
        print("canEdit", self.service_sheet.canEdit)
        if self.service_sheet.canEdit:
            updates = self.service_sheet.get_line('COLUMNS','A', sheet=self.client_id)
            if updates:
                self.service_sheet.erase_cells(self.client_id)
        else:
            new_changes_log_rows = self.service_sheet.get_line("COLUMNS",'A',sheet="changes_log")
            if len(new_changes_log_rows) > len(self.service_sheet.changes_log_rows):
                updates = new_changes_log_rows[-len(new_changes_log_rows)+len(self.service_sheet.changes_log_rows):]
                self.service_sheet.changes_log_rows = new_changes_log_rows
            else:
                updates = []
        # fix_print_with_import
        print("UPDATES", updates)
        for update in updates:
            decode_update = update.split("|")
            if decode_update[0] in ('new_feature', 'delete_feature', 'update_geometry', 'update_attributes'):
                sheet_feature = self.service_sheet.get_line('ROWS',decode_update[1])
                if decode_update[0] == 'new_feature':
                    feat = QgsFeature()
                    geom = QgsGeometry().fromWkt(zlib.decompress(base64.b64decode(sheet_feature[0])).decode("utf-8"))
                    feat.setGeometry(geom)
                    feat.setAttributes(sheet_feature[2:])
                    logger(( "updating from subscription, new_feature: " + str(self.lyr.dataProvider().addFeatures([feat]))))
                else:
                    sheet_feature_id = decode_update[1]
                    feat = next(self.lyr.getFeatures(QgsFeatureRequest(QgsExpression(' "FEATUREID" = %s' % sheet_feature_id))))
                    if   decode_update[0] == 'delete_feature':
                        # fix_print_with_import
                        print("updating from subscription, delete_feature: " + str(self.lyr.dataProvider().deleteFeatures([feat.id()])))
                    elif decode_update[0] == 'update_geometry':
                        update_set = {feat.id(): QgsGeometry().fromWkt(zlib.decompress(base64.b64decode(sheet_feature[0])).decode("utf-8"))}
                        # fix_print_with_import
                        print("update_set", update_set)
                        # fix_print_with_import
                        print("updating from subscription, update_geometry: " + str(self.lyr.dataProvider().changeGeometryValues(update_set)))
                    elif decode_update[0] == 'update_attributes':
                        new_attributes = sheet_feature_id[2:]
                        attributes_map = {}
                        for i in range(0, len(new_attributes)):
                            attributes_map[i] = new_attributes[i]
                        update_map = {feat.id(): attributes_map,}
                        # fix_print_with_import
                        print("update_map", update_map)
                        # fix_print_with_import
                        print("updating from subscription, update_attributes: " +(self.lyr.dataProvider().changeAttributeValues(update_map)))
            elif decode_update[0] == 'add_field':
                field_a1_notation = self.service_sheet.header_map[decode_update[1]]
                type_def = self.service_sheet.sheet_cell('settings!%s1' % field_a1_notation)
                type_def_decoded = type_def.split("|")
                new_field = QgsField(name=decode_update[1],type=int(type_def_decoded[0]), len=int(type_def_decoded[1]), prec=int(type_def_decoded[2]))
                # fix_print_with_import
                print("updating from subscription, add_field: ", + (self.lyr.dataProvider().addAttributes([new_field])))
                self.lyr.updateFields()
            elif decode_update[0] == 'delete_field':
                # fix_print_with_import
                print("updating from subscription, delete_field: " + str(self.lyr.dataProvider().deleteAttributes([self.lyr.dataProvider().fields().fieldNameIndex(decode_update[1])])))
                self.lyr.updateFields()
        self.lyr.triggerRepaint()
        bar.stop("local layer updated")

    def editing_started(self):
        '''
        Connect to the edit buffer so we can capture geometry and attribute
        changes
        '''
        # fix_print_with_import
        print("editing")
        self.update_from_subscription()
        self.bar = None
        if self.service_sheet.canEdit:
            self.activeThreads = 0
            self.editing = True
            self.lyr.geometryChanged.connect(self.buffer_geometry_changed)
            self.lyr.attributeValueChanged.connect(self.buffer_attributes_changed)
            self.lyr.beforeCommitChanges.connect(self.catch_deleted)
            self.lyr.beforeRollBack.connect(self.rollBack)
            self.invalidEdit.connect(self.rollBack)
            self.changes_log=[]
            self.locking_queue = []
            self.timer = 0
        else: #refuse editing if file is read only
            self.lyr.rollBack()

    def buffer_geometry_changed(self,fid,geom):
        '''
        Landing method for geometryChanged signal.
        When a geometry is modified, the row related to the modified feature is marked as modified by local user.
        Further edits to the modified feature are denied to other concurrent users
        :param fid:
        :param geom:
        '''
        if self.editing:
            self.lock_feature(fid)

    def buffer_attributes_changed(self,fid,attr_id,value):
        '''
        Landing method for attributeValueChanged signal.
        When an attribute is modified, the row related to the modified feature is marked as modified by local user.
        Further edits to the modified feature are denied to other concurrent users
        :param fid:
        :param attr_id:
        :param value:
        '''
        if self.editing:
            self.lock_feature(fid)


    def lock_feature(self, fid):
        """
        The row in google sheet linked to feature that has been modified is locked
        Filling the the STATUS column with the client_id.
        Further edits to the modified feature are denied to other concurrent users
        """
        if fid >= 0: # fid <0 means that the change relates to newly created features not yet present in the sheet
            self.locks_applied = None
            feature_locking = next(self.lyr.getFeatures(QgsFeatureRequest(fid)))
            locking_row_id = feature_locking[0]
            self.locking_queue.append(locking_row_id)
            _thread.start_new_thread(self.deferred_apply_locks, ())


    def deferred_apply_locks(self):
        if self.timer > 0:
            self.timer = 0
            return
        else:
            while self.timer < 100:
                self.timer += 1
                sleep(0.01)
            #APPLY_LOCKS
            self.deferredEdit.emit()
            #self.apply_locks()

    def apply_locks(self):
        if self.locks_applied:
            return
        self.locks_applied = True
        status_range = []
        for row_id in self.locking_queue:
            #print "locking_row_id",locking_row_id
            status_range.append(['STATUS', row_id])
        status_control = self.service_sheet.multicell(status_range)
        if "valueRanges" in status_control:
            mods = []
            for valueRange in status_control["valueRanges"]:
                if valueRange["values"][0][0] in ('()', None):
                    mods.append([valueRange["range"],0,self.client_id])
                    row_id = valueRange["range"].split('B')[-1]
            if mods:
                self.service_sheet.set_multicell(mods, A1notation=True)
        self.locking_queue = []
        self.timer = 0

    def ex_apply_locks(self):
        mods = []
        for row_id in self.locking_queue:
            #print "locking_row_id",locking_row_id
            status = self.service_sheet.cell('STATUS', row_id)
            if status in (None,''):
                self.service_sheet.set_cell('STATUS', row_id, self.client_id)
                #mods.append(['STATUS', row_id, self.client_id])
        if mods:
            self.service_sheet.set_multicell(mods)
        self.locking_queue = []
        self.timer = 0

    def ex_buffer_geometry_changed(self,fid,geom):
        '''
        Landing method for geometryChanged signal.
        When a geometry is modified, the row related to the modified feature is marked as modified by local user.
        Further edits to the modified feature are denied to other concurrent users
        :param fid:
        :param geom:
        '''
        if self.editing:
            if self.test:
                self.lock_feature(fid)
            else:
                # fix_print_with_import
                print("geom changed fid:",fid, self.locking_queue)
                _thread.start_new_thread(self.lock_feature, (fid,))
            #logger("active threads: "+ str( self.activeThreads))
            #self.lock_feature(fid)

    def ex_buffer_attributes_changed(self,fid,attr_id,value):
        '''
        Landing method for attributeValueChanged signal.
        When an attribute is modified, the row related to the modified feature is marked as modified by local user.
        Further edits to the modified feature are denied to other concurrent users
        :param fid:
        :param attr_id:
        :param value:
        '''
        if self.editing:
            if self.test:
                self.lock_feature(fid)
            else:
                # fix_print_with_import
                print("attr changed fid:",fid, self.locking_queue)
                _thread.start_new_thread(self.lock_feature, (fid,))
            #logger("active threads: "+ str( self.activeThreads))
            #print "active threads: ", self.activeThreads
            #self.lock_feature(fid)

    def ex_lock_feature(self,fid):
        """
        The row in google sheet linked to feature that has been modified is locked
        Filling the the STATUS column with the client_id.
        Further edits to the modified feature are denied to other concurrent users
        """
        self.activeThreads += 1
        if fid >= 0:
            self.locking_queue.append(fid)
            if self.activeThreads < 2: # fid <0 means that the change relates to newly created features not yet present in the sheet
                while self.locking_queue:
                    lock_fid = self.locking_queue[0]
                    self.locking_queue = self.locking_queue[1:]
                    feature_locking = next(self.lyr.getFeatures(QgsFeatureRequest(lock_fid)))
                    locking_row_id = feature_locking[0]
                    status = self.service_sheet.cell('STATUS', locking_row_id)
                    if status in (None,''):
                        self.service_sheet.set_cell('STATUS', locking_row_id, self.client_id)
                        #logger("feature #%s locked by %s" % (locking_row_id, self.client_id))

        self.activeThreads -= 1

    def rollBack(self):
        """
        before rollback changes status field is cleared and the edits from concurrent user are allowed
        """
        # fix_print_with_import
        print("ROLLBACK")
        try:
            self.lyr.geometryChanged.disconnect(self.buffer_geometry_changed)
        except:
            pass
        try:
            self.lyr.attributeValueChanged.disconnect(self.buffer_attributes_changed)
        except:
            pass
        self.renew_connection()
        self.clean_status_row()
        try:
            self.lyr.beforeRollBack.disconnect(self.rollBack)
        except:
            pass

        #self.lyr.geometryChanged.disconnect(self.buffer_geometry_changed)
        #self.lyr.attributeValueChanged.disconnect(self.buffer_attributes_changed)
        self.editing = False

    def editing_stopped(self):
        """
        Update the remote sheet if changes were committed
        """
        # fix_print_with_import
        print("EDITING_STOPPED")
        self.renew_connection()
        self.clean_status_row()
        if self.service_sheet.canEdit:
            self.service_sheet.advertise(self.changes_log)
        self.editing = False
        #if self.dirty:
        #    self.update_summary_sheet()
        #    self.dirty = None
        if self.bar:
            self.bar.stop("update to remote finished")

    def inspect_changes(self):
        '''
        here we can inspect changes before commit them
        self.deleted_list = []
        for deleted in self.lyr.editBuffer().deletedAttributeIds():
            self.deleted_list.append(self.lyr.fields().at(deleted).name())
        print self.deleted_list

        logger("attributes_added")
        for field in self.lyr.editBuffer().addedAttributes():
            print "ADDED FIELD", field.name()
            self.service_sheet.add_column([field.name()], fill_with_null = True)
        '''
        # fix_print_with_import
        print("INSPECT_CHANGES")
        pass

    def attributes_added(self, layer, added):
        """
        Landing method for attributeAdded.
        Fields (attribute) changed
        New colums are appended to the google drive spreadsheets creating remote colums syncronized with the local layer fields.
        Edits are advertized to other concurrent users for subsequent syncronization with remote table
        """
        logger("attributes_added")
        for field in added:
            logger( "ADDED FIELD %s" % field.name())
            self.service_sheet.add_column([field.name()], fill_with_null = True)
            self.service_sheet.add_column(["%d|%d|%d" % (field.type(), field.length(), field.precision())],child_sheet="settings", fill_with_null = None)
            self.changes_log.append('%s|%s' % ('add_field', field.name()))
        self.dirty = True

    def attributes_deleted(self, layer, deleted_ids):
        """
        Landing method for attributeDeleted.
        Fields (attribute) are deleted
        New colums are marked as deleted in the google drive spreadsheets.
        Edits are advertized to other concurrent users for subsequent syncronization with remote table
        """
        logger("attributes_deleted")
        for deleted in deleted_ids:
            deleted_name = self.service_sheet.mark_field_as_deleted(deleted)
            self.changes_log.append('%s|%s' % ('delete_field', deleted_name))
        self.dirty = True


    def features_added(self, layer, features):
        """
        Landing method for featureAdded.
        The new features are written adding rows to the google drive spreadsheets .
        Edits are advertized to other concurrent users for subsequent syncronization with remote table
        """
        logger("features added")

        for count,feature in enumerate(features):
            new_fid = self.service_sheet.new_fid()
            # fix_print_with_import
            print("NEWFID", new_fid, count)
            self.lyr.dataProvider().changeAttributeValues({feature.id() : {0: new_fid}})
            feature.setAttribute(0, new_fid+count)
            '''
            print "WKB", base64.b64encode(feature.geometry().asWkb())
            print "WKB", base64.b64encode(zlib.compress(feature.geometry().asWkb()))
            print "WKT", base64.b64encode(zlib.compress(feature.geometry().asWkt()))
            '''
            new_row_dict = {}.fromkeys(self.service_sheet.header,'()')
            new_row_dict['WKTGEOMETRY'] = base64.b64encode(zlib.compress(bytes(feature.geometry().asWkt(),'utf-8'))).decode('utf-8')
            new_row_dict['STATUS'] = '()'
            print()
            for i,item in enumerate(feature.attributes()):
                fieldName = self.lyr.fields().at(i).name()
                # fix_print_with_import
                print("FFFF", fieldName)
                try:
                    new_row_dict[fieldName] = item.toString(format = Qt.ISODate)
                except:
                    if not item or item == qgis.core.NULL:
                        new_row_dict[fieldName] = '()'
                    else:
                        new_row_dict[fieldName] = item
            new_row_dict['FEATUREID'] = '=ROW()' #assure correspondance between feature and sheet row
            print(new_row_dict)
            result = self.service_sheet.add_row(new_row_dict)
            print(result)
            sheet_new_row = int(result['updates']['updatedRange'].split('!A')[1].split(':')[0])
            self.changes_log.append('%s|%s' % ('new_feature', str(new_fid)))
        self.dirty = True

    def catch_deleted(self):
        """
        Landing method for beforeCommitChanges signal.
        The method intercepts edits before they were written to the layer so from deleted features
        can be extracted the feature id of the google drive spreadsheet related rows.
        The affected rows are marked as deleted and hidden away from the layer syncronization
        """
        self.bar = progressBar(self, 'updating local edits to remote')
        """ Features removed; but before commit """
        deleted_ids = self.lyr.editBuffer().deletedFeatureIds()
        if deleted_ids:
            deleted_mods = []
            for fid in deleted_ids:
                removed_feat = next(self.lyr.dataProvider().getFeatures(QgsFeatureRequest(fid)))
                removed_row = removed_feat[0]
                logger ("Deleting FEATUREID %s" % removed_row)
                deleted_mods.append(("STATUS",removed_row,'D'))
                self.changes_log.append('%s|%s' % ('delete_feature', str(removed_row)))
            if deleted_mods:
                self.service_sheet.set_protected_multicell(deleted_mods)
            self.dirty = True

    def geometry_changed(self, layer, geom_map):
        """
        Landing method for geometryChange signal.
        Features geometries changed
        The edited geometry, not locked by other users, are written to the google drive spreadsheets modifying the related rows.
        the WKT geometry definition is zipped and then base64 encoded for a compact storage
        (sigle cells string contents can't be larger the 50000 bytes)
        Edits are advertized to other concurrent users for subsequent syncronization with remote table
        """
        geometry_mod = []
        for fid,geom in geom_map.items():
            feature_changing = next(self.lyr.getFeatures(QgsFeatureRequest(fid)))
            row_id = feature_changing[0]
            wkt = geom.asWkt(precision=10)
            geometry_mod.append(('WKTGEOMETRY',row_id, base64.b64encode(zlib.compress(bytes(wkt,"utf-8"))).decode("utf-8")))
            logger ("Updated FEATUREID %s geometry" % row_id)
            self.changes_log.append('%s|%s' % ('update_geometry', str(row_id)))

        value_mods_result = self.service_sheet.set_protected_multicell(geometry_mod, lockBy=self.client_id)
        self.dirty = True

    def attributes_changed(self, layer, changes):
        """
        Landing method for attributeChange.
        Attribute values changed
        Edited feature, not locked by other users, are written to the google drive spreadsheets modifying the related rows.
        Edits are advertized to other concurrent users for subsequent syncronization with remote table
        """
        if not self.doing_attr_update:
            #print "changes",changes
            attribute_mods = []
            for fid,attrib_change in changes.items():
                feature_changing = next(self.lyr.getFeatures(QgsFeatureRequest(fid)))
                row_id = feature_changing[0]
                logger ( "Attribute changing FEATUREID: %s" % row_id)
                for attrib_idx, new_value in attrib_change.items():
                    fieldName = QgsProject.instance().mapLayer(layer).fields().field(attrib_idx).name()
                    if fieldName == 'FEATUREID':
                        logger("can't modify FEATUREID")
                        continue
                    try:
                        cleaned_value = new_value.toString(format = Qt.ISODate)
                    except:
                        if not new_value or new_value == qgis.core.NULL:
                            cleaned_value = '()'
                        else:
                            cleaned_value = new_value
                    attribute_mods.append((fieldName,row_id, cleaned_value))
                self.changes_log.append('%s|%s' % ('update_attributes', str(row_id)))

            if attribute_mods:
                attribute_mods_result = self.service_sheet.set_protected_multicell(attribute_mods, lockBy=self.client_id)
            self.dirty = True

    def clean_status_row(self):
        status_line = self.service_sheet.get_line("COLUMNS","B")
        clean_status_mods = []
        for row_line, row_value in enumerate(status_line):
            if row_value == self.client_id:
                clean_status_mods.append(("STATUS",row_line+1,'()'))
        value_mods_result = self.service_sheet.set_multicell(clean_status_mods)
        return value_mods_result

    def unsubscribe(self):
        '''
        When a read/write layer is removed from the legend the remote subscription sheet is removed and update summary sheet if dirty
        '''
        self.renew_connection()
        self.service_sheet.unsubscribe()

    def qgis_layer_to_csv(self,qgis_layer):
        '''
        method to transform the specified qgis layer in a csv object for uploading
        :param qgis_layer:
        :return: csv object
        '''
        stream = io.BytesIO()
        writer = csv.writer(stream, delimiter=',', quotechar='"', lineterminator='\n')
        row = ["WKTGEOMETRY","FEATUREID","STATUS"]
        for feat in qgis_layer.getFeatures():
            for field in feat.fields().toList():
                row.append(field.name().encode("utf-8"))
            break
        writer.writerow(row)
        for feat in qgis_layer.getFeatures():
            row = [base64.b64encode(zlib.compress(bytes(feat.geometry().asWkt(precision=10),"utf-8"))).decode("utf-8"),feat.id(),"()"]
            for field in feat.fields().toList():
                if feat[field.name()] == qgis.core.NULL:
                    content = "()"
                else:
                    if type(feat[field.name()]) == str:
                        content = feat[field.name()].encode("utf-8")
                    else:
                        content = feat[field.name()]
                row.append(content)
            writer.writerow(row)
        #print stream.getvalue()
        stream.seek(0)
        #csv.reader(stream, delimiter=',', quotechar='"', lineterminator='\n')
        return stream

    def qgis_layer_to_list(self,qgis_layer):
        '''
        method to transform the specified qgis layer in list of rows (field/value) dicts for uploading
        :param qgis_layer:
        :return: row list object
        '''
        row = ["WKTGEOMETRY","STATUS","FEATUREID"]
        for feat in qgis_layer.getFeatures():
            for field in feat.fields().toList():
                row.append(field.name())
                #row.append(str(field.name()).encode("utf-8"))# slugify(field.name())
            break
        rows = [row]
        for feat in qgis_layer.getFeatures():
            row = [base64.b64encode(zlib.compress(bytes(feat.geometry().asWkt(precision=10),"utf-8"))).decode("utf-8"),"()","=ROW()"] # =ROW() perfect row/featureid correspondance
            if len(row[0]) > 10000:
                # fix_print_with_import
                print(feat.id, len(row))
            if len(row[0]) > 50000: # ignore features with geometry > 50000 bytes zipped
                continue
            for field in feat.fields().toList():
                if feat[field.name()] == qgis.core.NULL:
                    content = "()"
                else:
                    if type(feat[field.name()]) == str:
                        content = feat[field.name()] #feat[field.name()].encode("utf-8")
                    elif field.typeName() in ('Date', 'Time'):
                        content = feat[field.name()].toString(format = Qt.ISODate)
                    else:
                        content = feat[field.name()]
                row.append(content)
            rows.append(row)
        #csv.reader(stream, delimiter=',', quotechar='"', lineterminator='\n')
        return rows

    def saveFieldTypes(self,fields):
        '''
        writes the layer field types to the setting sheet
        :param fields:
        :return:
        '''
        types_array = ["s1","s2","4|4|0"] #default featureId type to longint
        for field in fields.toList():
            types_array.append("%d|%d|%d" % (field.type(), field.length(), field.precision()))
        # fix_print_with_import
        print("FIELDTYPES",self.service_sheet.update_cells('settings!A1',types_array))

    def layer_style_to_xml(self,qgis_layer):
        '''
        saves qgis style to the setting sheet
        :param qgis_layer:
        :return:
        '''
        XMLDocument = QDomDocument("qgis_style")
        XMLStyleNode = XMLDocument.createElement("style")
        XMLDocument.appendChild(XMLStyleNode)
        error = None
        rw_context = QgsReadWriteContext()
        rw_context.setPathResolver( QgsProject.instance().pathResolver() )
        qgis_layer.writeSymbology(XMLStyleNode, XMLDocument, error,rw_context)
        xmldoc = XMLDocument.toString(1)
        return xmldoc

    def SLD_to_xml(self,qgis_layer):
        '''
        saves SLD style to the setting sheet. Not used, keeped here for further extensions.
        :param qgis_layer:
        :return:
        '''
        XMLDocument = QDomDocument("sld_style")
        error = None
        qgis_layer.exportSldStyle(XMLDocument, error)
        xmldoc = XMLDocument.toString(1)
        return xmldoc

    def xml_to_layer_style(self,qgis_layer,xml):
        '''
        retrieve qgis style from the setting sheet
        :param qgis_layer:
        :return:
        '''
        XMLDocument = QDomDocument()
        error = None
        XMLDocument.setContent(xml)
        XMLStyleNode = XMLDocument.namedItem("style") 
        rw_context = QgsReadWriteContext()
        rw_context.setPathResolver( QgsProject.instance().pathResolver() )
        qgis_layer.readSymbology(XMLStyleNode, error, rw_context)

    def layer_style_to_json(self, qgis_layer):
        mapbox_style = toMapboxgl([qgis_layer])
        # fix_print_with_import
        print(mapbox_style)
        return json.dumps(mapbox_style)

    def get_gdrive_id(self):
        '''
        returns spreadsheet_id associated with layer
        :return: spreadsheet_id associated with layer
        '''
        return self.spreadsheet_id

    def get_service_drive(self):
        '''
        returns the google drive wrapper object associated with layer
        :return: google drive wrapper object
        '''
        return self.service_drive

    def get_service_sheet(self):
        '''
        returns the google spreadsheet wrapper object associated with layer
        :return: google spreadsheet wrapper object
        '''
        return self.service_sheet

    def get_layer_metadata(self):
        '''
        builds a metadata dict of the current layer to be stored in summary sheet
        '''
        #fields = collections.OrderedDict()
        fields = ""
        for field in self.lyr.fields().toList():
            fields += field.name()+'_'+QVariant.typeToName(field.type())+'|'+str(field.length())+'|'+str(field.precision())+' '
        #metadata = collections.OrderedDict()
        metadata = [
            ['layer_name', self.lyr.name(),],
            ['gdrive_id', self.service_sheet.spreadsheetId,],
            ['geometry_type', self.geom_types[self.lyr.geometryType()],],
            ['features', "'%s" % str(self.lyr.featureCount()),],
            ['extent', self.lyr.extent().asWktCoordinates(),],
            ['fields', fields,],
            ['srid', self.lyr.crs().authid(),],
            ['proj4_def', "'%s" % self.lyr.crs().toProj4(),]
        ]
        return metadata

    def update_summary_sheet(self):
        '''
        Creates a summary sheet with thumbnail, layer metadata and online view link
        '''
        #create a layer snapshot and upload it to google drive
        mapbox_style = self.service_sheet.sheet_cell('settings!A5')
        if not mapbox_style:
            # fix_print_with_import
            print("migrating mapbox style")
            self.service_sheet.set_style_mapbox(self.layer_style_to_json(self.lyr))
        if not self.dirty:
            return
        canvas = QgsMapCanvas()
        canvas.resize(QSize(300,300))
        canvas.setCanvasColor(Qt.white)
        canvas.setExtent(self.lyr.extent())
        canvas.setLayers([self.lyr]) #([QgsMapCanvasLayer(self.lyr)])
        canvas.refresh()
        canvas.update()
        settings = canvas.mapSettings()
        settings.setLayers([self.lyr])
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        image = job.renderedImage()
        tmp_path = os.path.join(self.parent.plugin_dir,self.service_sheet.name+".png")
        image.save(tmp_path,"PNG")
        image_istances = self.service_drive.list_files(mimeTypeFilter='image/png',filename=self.service_sheet.name+".png")
        for imagename, image_props in image_istances.items():
            # fix_print_with_import
            print(imagename, image_props['id'])
            self.service_drive.delete_file(image_props['id'])
        result = self.service_drive.upload_image(tmp_path)
        # fix_print_with_import
        print("UPLOADED", result)
        self.service_drive.add_permission(result['id'],'anyone','reader')
        webLink = 'https://drive.google.com/uc?export=view&id='+result['id']
        os.remove(tmp_path)
        # fix_print_with_import
        print('result',result,webLink)

        #update layer metadata
        summary_id = self.service_sheet.add_sheet('summary', no_grid=True)
        self.service_sheet.erase_cells('summary')
        metadata = self.get_layer_metadata()
        range = 'summary!A1:B8'
        update_body = {
            "range": range,
            "values": metadata,
        }
        # fix_print_with_import
        print("update", self.service_sheet.service.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id,range=range, body=update_body, valueInputOption='USER_ENTERED').execute())

        #merge cells to visualize snapshot and aaply image snapshot
        request_body = {
            'requests': [{
                'mergeCells': {
                    "range": {
                        "sheetId": summary_id,
                        "startRowIndex": 9,
                        "endRowIndex": 32,
                        "startColumnIndex": 0,
                        "endColumnIndex": 9,
                    },
                "mergeType": 'MERGE_ALL'
                }
            }]
        }
        # fix_print_with_import
        print("merge", self.service_sheet.service.spreadsheets().batchUpdate(spreadsheetId=self.spreadsheet_id, body=request_body).execute())
        # fix_print_with_import
        print("image", self.service_sheet.set_sheet_cell('summary!A10','=IMAGE("%s",3)' % webLink))

        permissions = self.service_drive.file_property(self.spreadsheet_id,'permissions')
        for permission in permissions:
            if permission['type'] == 'anyone':
                public = True
                break
            else:
                public = False
        if public:
            range = 'summary!A9:B9'
            update_body = {
                "range": range,
                "values": [['public link', "https://enricofer.github.io/GooGIS2CSV/converter.html?spreadsheet_id="+self.spreadsheet_id]]
            }
            # fix_print_with_import
            print("update_public_link", self.service_sheet.service.spreadsheets().values().update(spreadsheetId=self.spreadsheet_id,range=range, body=update_body, valueInputOption='USER_ENTERED').execute())

        #hide worksheets except summary
        sheets = self.service_sheet.get_sheets()
        #self.service_sheet.toggle_sheet('summary', sheets['summary'], hidden=None)
        for sheet_name,sheet_id in sheets.items():
            if not sheet_name == 'summary':
                # fix_print_with_import
                print(sheet_name, sheet_id)
                self.service_sheet.toggle_sheet(sheet_name, sheet_id, hidden=True)







        

