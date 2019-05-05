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
import os 
import site
import sys

sys.path.append(os.path.dirname(__file__))

site.addsitedir(os.path.join(os.path.dirname(__file__),'extlibs'))

if not hasattr(sys, 'argv'):
    sys.argv  = ['']

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load CSVProvider class from file CSVProvider.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .gdrive_provider import Google_Drive_Provider
    return Google_Drive_Provider(iface)
