Ext.require([

    'Ext.slider.Single',
    'Ext.form.Panel',
    'Ext.panel.Panel',
    'Ext.Viewport',
    'GeoExt.component.Map',
    //'Ext.ux.grid.feature.Searching'
]);

Ext.Loader.loadScript({
    url: 'https://rawgit.com/geoext/geoext3/master/classic/selection/FeatureModel.js'
});

var layer_projection = 'EPSG:4326';
var view_projection = 'EPSG:3857';
var getfeature_popup;
var googis_map;
var googis_layer;
var content_store;
var detail_store;
var public_layers;
var georef_overlay;
var layer_collection;
var form, group_panel, detail_panel, description;
var zoomto;

var publayers_id = decompress('eJwzLE9OccnNKkjKNCkoy6vIdy13S0p2D3QLjUwJMDZ1ccnO9dLVLUwPM4wsMQEAYh0PCA==');

window.googleDocCallback = function () { return true; };

function registerEPSGId(newProjCode, proj4def){
    console.log("PROJ4 DEF:",newProjCode, proj4def)
    if (newProjCode != 'EPSG:3858' && newProjCode != 'EPSG:4326'){
        proj4.defs(newProjCode, proj4def);
        ol.proj.proj4.register(proj4);
        var layer_projection = ol.proj.get(newProjCode);
    }
}

function decompress(b64_zipped){
    // Decode base64 (convert ascii to binary)
    var strData     = atob(b64_zipped);
    // Convert binary string to character-number array
    var charData    = strData.split('').map(function(x){return x.charCodeAt(0);});
    // Turn number array into byte-array
    var binData     = new Uint8Array(charData);
    // Pako magic
    var inflated    = pako.inflate(binData);
    // Convert gunzipped byteArray back to ascii string:
    return String.fromCharCode.apply(null, new Uint16Array(inflated));
} 

var yellowStyle = new ol.style.Style({
    fill: new ol.style.Fill({
        color: 'rgba(255, 255, 255, 0)'
    }),
    stroke: new ol.style.Stroke({
        color: '#ffff00',
        width: 2
    })
})

var redStyle = new ol.style.Style({
    fill: new ol.style.Fill({
        color: 'rgba(255, 255, 255, 0)'
    }),
    stroke: new ol.style.Stroke({
        color: '#ff0000',
        width: 4
    })
})

Ext.application({
    name: 'googis',
    launch: function() {

        function load_googis_sheet(spreadsheet_id) {
            $('#downloading').css('display', 'block');
            console.log('https://docs.google.com/spreadsheets/d/'+ spreadsheet_id +'/pubhtml?callback=googleDocCallback');
            Tabletop.init( { key: 'https://docs.google.com/spreadsheets/d/'+ spreadsheet_id +'/pubhtml?callback=googleDocCallback',
                            callback: showInfo,
                            simpleSheet: false } )
        }   

        function showInfo(data, tabletop) {
            //alert('Successfully processed!')
            $('#downloading').css('display', 'none');
            $('.progress').css('display', 'block');
            //console.log(tabletop);
            console.log(data);

            var $progressBar = $('.progress-bar');
            var WKT_format = new ol.format.WKT();
            var GeoJSON_format = new ol.format.GeoJSON();
            layer_collection = new ol.Collection();
            public_layers = {};
            var data_array = data["keys"].toArray();
            var i, k, rows = data_array.length;
            console.log(data_array);
            for (i=0; i<rows; ++i) {
                row = data_array[i];
                var metadata = JSON.parse(decompress(row[1]))
                console.log(row[0],metadata);
                if ('extent' in metadata) {
                    var extent_txt = "[" + metadata.extent.replace(/\s/g,",").replace(",,",",") + "]"
                    var extent = JSON.parse(extent_txt)
                    metadata.fid = row[0]
                    public_layers[row[0]] = metadata;
                    var extent_geom = ol.geom.Polygon.fromExtent(extent);
                    var pub_layer_feat = new ol.Feature({
                        geometry: extent_geom.transform(layer_projection,view_projection),
                        name: metadata.layer_name
                    });
                    pub_layer_feat.setProperties(metadata)
                    layer_collection.push(pub_layer_feat);
                }
                setTimeout(function(){
                    progress_percent = Math.trunc(i*100/rows);
                    $progressBar.css('width', progress_percent.toString()+'%');
                }, 50);  

            }

            googis_layer = new ol.layer.Vector({
                source: new ol.source.Vector({
                    features: layer_collection,
                    projection: view_projection
                }),
                title: "GOOGIS public layers",
                visible: true,
                style: yellowStyle
            });

            georef_overlay = new ol.layer.Image({
              title: 'preview overlay',
            });
            
            googis_map.addLayer(googis_layer);
            googis_map.addLayer(georef_overlay);
                
            var googis_extent = googis_layer.getSource().getExtent();
            googis_map.getView().fit(googis_extent, googis_map.getSize());
            
            getfeature_popup = new ol.Overlay.Popup (
                {	popupClass: "default", //"tooltips", "warning" "black" "default", "tips", "shadow",
                    closeBox: true,
                    positioning: 'auto',
                    autoPan: true,
                    autoPanAnimation: { duration: 250 }
                });
            googis_map.addOverlay(getfeature_popup);
            
            
            googis_map.on('click', function(evt) {

                // Hide existing popup and reset it's offset
                getfeature_popup.hide();
                getfeature_popup.setOffset([0, 0]);

                // Attempt to find a feature in one of the visible vector layers
                var feature = googis_map.forEachFeatureAtPixel(evt.pixel, function(feature, layer) {
                    return feature;
                });

                if (feature) {

                    var coord = feature.getGeometry().getFirstCoordinate();//getCoordinates();
                    var props = feature.getProperties();
                    var info = '<div class="xxx"><small><table>';

                    for (var key in props) {
                        if (props.hasOwnProperty(key)&&(key !='geometry')) {
                            info += "<tr>"
                            info += "<td><strong>" + key + "</strong></td>"
                            info += '<td style="padding-left:8px;">' + props[key] + '</td>';
                            info += "</tr>"
                        }
                    }

                    info += "</table></small></div>";

                    getfeature_popup.setOffset([0, -21]);
                    getfeature_popup.show(coord, info);

                }

            });

            googis_map.on('moveend', syncSourceView);
            googis_map.on('zoomend', syncSourceView);
            
            $('.progress').css('display', 'none');
            $('#completed').css('display', 'none');
        }

        //window.addEventListener('DOMContentLoaded', init)
        
        zoomto = function (extent_string) {
            extent = ol.proj.transformExtent(JSON.parse(extent_string), 'EPSG:4326', 'EPSG:3857')
            console.log(extent)
            googis_map.getView().fit(extent, googis_map.getSize());
        }

        function gup(name) {
            name = name.replace(/[\[]/,"\\\[").replace(/[\]]/,"\\\]");
            var regexS = "[\\?&]"+name+"=([^&#]*)";
            var regex = new RegExp( regexS );
            var results = regex.exec( window.location.href );
            if( results == null )
                return "";
            else
                return results[1];
        }

        function syncSourceView () {
            var view_collection = new ol.Collection();
            var current_extent = googis_map.getView().calculateExtent(googis_map.getSize());
            googis_layer.getSource().forEachFeatureInExtent(current_extent, function(feature){
                view_collection.push(feature);
            }); 

            // create feature store by passing a feature collection
            content_store = Ext.create('GeoExt.data.store.Features', {
                fields: ['layer_name','fid'],
                model: 'GeoExt.data.model.Feature',
                features: view_collection,
                map: googis_map,
                createLayer: false,
                style: yellowStyle
            });

            Ext.ComponentMgr.get('visible_layers').setStore(content_store);  
        }

        googis_map = new ol.Map({
            layers: [
                    new ol.layer.Tile({
                        title: "OSM",
                        baseLayer: true,
                        visible: false,
                        source: new ol.source.OSM()
                    }),
                    new ol.layer.Tile({
                        title: "OSM monochrome",
                        baseLayer: true,
                        visible: true,
                        source: new ol.source.XYZ({
                            "url": "https://tiles.wmflabs.org/bw-mapnik/{z}/{x}/{y}.png"
                        })
                    })
            ],
            controls: ol.control.defaults().extend([
                new ol.control.MousePosition(),
                new ol.control.OverviewMap(),
                new ol.control.LayerSwitcher()
            ])
        });
        
        load_googis_sheet(publayers_id)

        mapComponent = Ext.create('GeoExt.component.Map', {
            map: googis_map
        });

        mapPanel = Ext.create('Ext.panel.Panel', {
            region: 'center',
            layout: 'fit',
            items: [mapComponent]
        });

        description = Ext.create('Ext.panel.Panel', {
            contentEl: 'description',
            title: 'Description',
            height: '1000',
            border: false,
            bodyPadding: 5
        });

        var searching = {
            ftype: 'searching',
            minChars: 2,
            mode: 'local'
         };

        list_panel = Ext.create('Ext.grid.Panel', {
            title: 'public_layers',
            id: 'visible_layers',
            features: [searching],
            hideHeaders:true, 
            store: content_store, //Ext.data.StoreManager.lookup('content_store'),
            columns: [
                { text: 'layer', dataIndex: 'layer_name', flex: 1 }
            ],
            height: 500,
            width: 300,
            selModel: {
                type: 'featuremodel',
                mode: 'SINGLE',
                mapSelection: false,
                map: googis_map,
                selectStyle: redStyle
            },
            listeners: {
                'rowclick': function(grd, record) {
                    console.log(record.data.fid);
                    var layer_clicked_data = public_layers[record.data.fid];
                    console.log(layer_clicked_data);
                    var details = [
                        {key: "View layer", value: ""}, //"?spreadsheet_id="+layer_clicked_data["gdrive_id"]},
                        {key: "Zoom to extent", value: ""} //layer_clicked_data["keymap_extent"]
                    ]

                    detail_panel.setTitle(layer_clicked_data["layer_name"])

                    for(var key in layer_clicked_data){
                        if (!layer_clicked_data.hasOwnProperty(key)) continue;
                        details.push({key:key,value:layer_clicked_data[key]})
                    }
                    //details["extent"] = ">" + details["extent"]

                    detail_store = Ext.create('Ext.data.Store', {
                        storeId: 'details',
                        fields:[ 'key','value'],
                        data: details,
                        autoLoad: true
                    });
                    Ext.ComponentMgr.get('layer_detail').setStore(detail_store);  

                    var georef_overlay_source =  new ol.source.ImageStatic({
                        url: layer_clicked_data.keymap,
                        projection: layer_projection,
                        imageExtent: JSON.parse(layer_clicked_data.keymap_extent),
                    })
                    georef_overlay.setSource(georef_overlay_source)
                    console.log(layer_clicked_data.keymap,JSON.parse(layer_clicked_data.keymap_extent))
                }
            }
        });

        detail_panel = Ext.create('Ext.grid.Panel', {
            title: 'Details',
            id: 'layer_detail',
            store: Ext.data.StoreManager.lookup('detail_store'),
            hideHeaders:true, 
            columns: [
                { 
                    text: 'key', 
                    dataIndex: 'key', 
                    flex: 1,
                    renderer: function(value, metaData, record, row, col, store, gridView){
                        // not supported yet
                        switch (value) {
                            case "View layer":
                                return '<a href="#">View layer</a>';
                            case "Zoom to extent": 
                                return '<a href="#">Zoom to extent</a>'
                            default:
                                return value
                        }
                    } 
                },
                { 
                    text: 'value', 
                    dataIndex: 'value', 
                    flex: 1
                },
            ],
            height: 500,
            width: 300,
            listeners: {
                rowclick: function(grd, record) {
                    switch (record.data["key"]) {
                        case "View layer":
                            var record = this.store.findRecord('key', 'gdrive_id')
                            if (!record) {
                                record = this.store.findRecord('key', 'fid')
                            }
                            if (record){
                                window.open('https://enricofer.github.io/gdrive_provider/weblink/converter.html?spreadsheet_id=' + record.data["value"], '_blank');
                            }
                            break;
                        case "Zoom to extent":
                            var record = this.store.findRecord('key', 'keymap_extent')
                            if (record) {
                                list_panel.getSelectionModel().deselectAll();
                                zoomto(record.data["value"]);
                            }
                            break;
                    }
                }
            },
            viewConfig : {
                enableTextSelection: true
            }
        });

        group_panel = Ext.create('Ext.panel.Panel', {
            region: 'east',
            width: 300,
            height: 1000,
            layout: {
                type: 'vbox',
                align: 'stretch'
            },
            items: [
                //description,
                list_panel,
                detail_panel,
            ]
        });


        Ext.create('Ext.Viewport', {
            layout: 'border',
            items: [
                mapPanel,
                group_panel
            ]
        });

}
});