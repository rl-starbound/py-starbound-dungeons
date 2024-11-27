from .common import make_dst_dir

from bisect import bisect_left

import csv
import json
import pytiled_parser
import re
import sys


# Ignore uninteresting vanilla stagehands.
ignored_stagehands = [
    'apexmissionbattleeffect', 'apexmissioncallscriptsensor', 'bossdooropener',
    'bossmusic', 'bossplanner', 'cultistbeamposition',
    'cultistflyingslashposition', 'cultistidleslashposition',
    'cultistlowerdashposition', 'cultistsphereposition',
    'cultistupperdashposition', 'glitchmissionmanager',
    'glitchmissionspawnpoint', 'interactobject', 'mechbeacon', 'messenger',
    'monsterspawn', 'npcspawn', 'objecttracker', 'protectoratemanager',
    'scanclue', 'storageclue', 'vaultitemspawn', 'vaultnpcspawn', 'waypoint'
]

# Some Tiled dungeon parts are referenced by multiple dungeons. Indexing
# them multiple times provides no benefit and takes time, so keep a list
# of which parts were already seen.
seen_tiled_parts = set()


def clearBit(i, offset):
    mask = ~(1 << offset)
    return(i & mask)


def get_tiled_property(obj, name, ptype='string'):
    if isinstance(obj.properties, dict):
        # old style properties
        if ptype == 'string': return obj.properties.get(name)
    elif isinstance(obj.properties, list):
        # new style properties
        for prop in obj.properties:
            if isinstance(prop, dict):
                if prop['name'] == name and prop['type'] == ptype:
                    return prop['value']
            else:
                raise Exception('Invalid Tiled property')
        else:
            return None
    else:
        raise Exception('Invalid Tiled property')


def make_dungeon_part_tileset_index(dungeon_tilesets):
    tilesets = []
    tileset_firstgid_index = []
    tileset_lastgid_index = []
    prev_tileset = None
    for firstgid, tileset in dungeon_tilesets.items():
        tileset_firstgid_index.append(firstgid)
        if prev_tileset is not None:
            tilesets.append(prev_tileset)
            tileset_lastgid_index.append(firstgid - 1)
        prev_tileset = tileset
    if prev_tileset is not None:
        tilesets.append(prev_tileset)
        tileset_lastgid_index.append(2 ** 32 - 1)
    assert len(tilesets) == len(tileset_firstgid_index)
    assert len(tilesets) == len(tileset_lastgid_index)
    return {
        'tilesets': tilesets,
        'firstgids': tileset_firstgid_index,
        'lastgids': tileset_lastgid_index
    }


def unflip_object(raw_gid):
    # This should be handled by the pytiled_parser library.
    # https://doc.mapeditor.org/en/stable/reference/tmx-map-format/#tile-flipping
    return clearBit(clearBit(clearBit(raw_gid, 29), 31), 30)


def unflip_tile_layer(data):
    tile_grid = []
    for row in data:
        row_data = []
        for val in row:
            # This should be handled by the pytiled_parser library.
            # https://doc.mapeditor.org/en/stable/reference/tmx-map-format/#tile-flipping
            row_data.append(clearBit(clearBit(clearBit(val, 29), 31), 30))
        assert len(row) == len(row_data)
        tile_grid.append(row_data)
    assert len(data) == len(tile_grid)
    return tile_grid


def add_tileset(tilesets, tileset):
    '''
    Regardless of beta or post-1.0 version, Starbound tilesets use a
    format that existed before Tiled went 1.0. This older format cannot
    be parsed by pytiled-parser, so it is ignored. We will have to parse
    it manually and provide the data that we need.
    '''
    if tilesets.get(tileset['name']) is not None:
        # BETA - Some tileset names are duplicated.
        print('WARNING: duplicate tileset names: {}'.format(tileset['name']))
    else:
        tilesets[tileset['name']] = {}
    for offset, tile in tileset['tileproperties'].items():
        tilesets[tileset['name']][offset] = {
            'offset': offset, 'content': '', 'type': 'unknown'
        }
        if tile.get('invalid', '') == 'true':
            tilesets[tileset['name']][offset]['type'] = 'invalid'
        elif tile.get('liquid'):
            tilesets[tileset['name']][offset]['type'] = 'liquid'
            tilesets[tileset['name']][offset]['content'] = tile['liquid']
        elif tile.get('material'):
            tilesets[tileset['name']][offset]['type'] = 'material'
            tilesets[tileset['name']][offset]['content'] = tile['material']
        elif tile.get('object'):
            tilesets[tileset['name']][offset]['type'] = 'object'
            tilesets[tileset['name']][offset]['content'] = tile['object']


def process_embedded_tilesets(dungeon_json):
    tilesets = {}
    for tileset in dungeon_json['tilesets']:
        if not tileset.get('source'):
            add_tileset(tilesets, tileset)
    return tilesets


def process_external_tilesets(src_dir):
    tilesets = {}

    tsdir = src_dir / 'tilesets'
    if not tsdir.is_dir():
        # These assets do not contain any tilesets. This will become an
        # error if Tiled dungeons with external tilesets exist in these
        # assets.
        return tilesets

    for relative_path in tsdir.glob('**/*.json'):
        tileset = None
        with open(tsdir / relative_path, 'rb') as fh:
            tileset = json.loads(fh.read())
        add_tileset(tilesets, tileset)

    return tilesets


def tiled_parse_mod(csvout, partialRow, obj, mods):
    modType = get_tiled_property(obj, 'mod')
    if modType:
        moddedMaterials = []
        moddedMaterial = get_tiled_property(obj, 'material')
        if moddedMaterial:
            moddedMaterials.append(moddedMaterial)
        else:
            moddedMaterial = get_tiled_property(obj, 'back')
            if moddedMaterial:
                moddedMaterials.append(moddedMaterial)
            moddedMaterial = get_tiled_property(obj, 'front')
            if moddedMaterial:
                moddedMaterials.append(moddedMaterial)
        if not moddedMaterials:
            # It might just be a mod with no defined material.
            moddedMaterials.append('')
        for moddedMaterial in moddedMaterials:
            modCombo = '{}:{}'.format(modType, moddedMaterial)
            if not modCombo in mods:
                row = partialRow.copy()
                row.extend(['mod', modType])
                if moddedMaterial:
                    row.append('moddedMaterial={}'.format(moddedMaterial))
                csvout.writerow(row)
                mods.add(modCombo)
        return True


def tiled_parse_monster(csvout, partialRow, obj):
    monsterType = get_tiled_property(obj, 'monster')
    if monsterType:
        row = partialRow.copy()
        row.extend(['monster', monsterType])
        csvout.writerow(row)
        return True


def tiled_parse_npc(csvout, partialRow, obj):
    npcSpecies = get_tiled_property(obj, 'npc')
    if npcSpecies:
        npcSpecies = re.sub(r',\s*', ';', npcSpecies)
        npcType = get_tiled_property(obj, 'typeName')
        if not npcType:
            raise Exception('Malformed npc')
        row = partialRow.copy()
        row.extend(['npc', npcType, 'species={}'.format(npcSpecies)])
        csvout.writerow(row)
        return True


def tiled_parse_stagehand(csvout, partialRow, obj):
    stagehandType = get_tiled_property(obj, 'stagehand')
    if stagehandType == 'questlocation':
        parameters = get_tiled_property(obj, 'parameters')
        if parameters:
            parameters = json.loads(parameters)
            locationType = parameters.get('locationType')
            if not locationType:
                raise Exception('Malformed questlocation')
            row = partialRow.copy()
            row.extend([
                'stagehand', stagehandType, 'location={}'.format(locationType)
            ])
            csvout.writerow(row)
            return True
        else:
            raise Exception('Malformed questlocation')
    elif stagehandType == 'radiomessage':
        parameters = get_tiled_property(obj, 'parameters')
        if parameters:
            parameters = json.loads(parameters)
            radioMessage = parameters\
                .get('radioMessage', ';'.join(parameters\
                .get('radioMessages', [])))
            if not radioMessage:
                raise Exception('Malformed radiomessage')
            row = partialRow.copy()
            row.extend([
                'stagehand', stagehandType, 'message={}'.format(radioMessage)
            ])
            csvout.writerow(row)
            return True
        else:
            raise Exception('Malformed radiomessage')
    elif stagehandType in ignored_stagehands:
        return True
    elif not not stagehandType:
        print('INFO: ignored stagehand type: {}'.format(stagehandType))
        return True


def tiled_parse_vehicle(csvout, partialRow, obj):
    vehicleType = get_tiled_property(obj, 'vehicle')
    if vehicleType:
        row = partialRow.copy()
        row.extend(['vehicle', vehicleType])
        csvout.writerow(row)
        return True


def get_tile(embedded_tilesets, external_tilesets, tileset_name, offset):
    try:
        return embedded_tilesets[tileset_name][offset]
    except KeyError as e:
        return external_tilesets[tileset_name][offset]


def index_tiled_dungeon_part(
    src_dir, dst_dir, partpath, partfile, external_tilesets
):
    if partpath / partfile in seen_tiled_parts: return

    dst_path = make_dst_dir(src_dir, dst_dir, partpath)

    # BETA - Some beta assets contain embedded, rather than external,
    # tileset definitions.
    dungeon_json = None
    try:
        with open(partpath / partfile, 'rb') as fh:
            dungeon_json = json.loads(fh.read())
    except FileNotFoundError as e:
        # BETA - incorrect file case.
        partfile = partfile.lower()
        with open(partpath / partfile, 'rb') as fh:
            dungeon_json = json.loads(fh.read())
    embedded_tilesets = process_embedded_tilesets(dungeon_json)

    try:
        dungeon_part = pytiled_parser.parse_map(partpath / partfile)
    except KeyError as e:
        # BETA - Some embedded tilesets are missing parameters.
        if e.args and e.args[0] == 'tilecount':
            print('ERROR: Malformed tilesets in Tiled map: {}'.format(
                partpath / partfile))
            return
        else: raise
    tileset_index = make_dungeon_part_tileset_index(dungeon_part.tilesets)

    with open(dst_path / "{}.csv".format(partfile), 'w') as fh:
        csvout = csv.writer(fh, lineterminator='\n')

        layer_idx = 0
        for layer in dungeon_part.layers:
            if isinstance(layer, pytiled_parser.TileLayer):
                tile_data = unflip_tile_layer(layer.data)
                layer_tiles = set()
                for row in tile_data:
                    for gid in row:
                        if gid == 0:
                            # 0 == no tile at this coordinate
                            continue
                        if gid in layer_tiles:
                            # Index only one instance of each tile type
                            # in each layer to save space and time.
                            continue
                        tileset_idx = bisect_left(tileset_index['lastgids'], gid)
                        tileset = tileset_index['tilesets'][tileset_idx]
                        tileset_firstgid = tileset_index['firstgids'][tileset_idx]
                        tileset_offset = gid - tileset_firstgid
                        assert tileset_offset >= 0
                        assert tileset_offset < tileset.tile_count
                        tile = get_tile(
                            embedded_tilesets, external_tilesets,
                            tileset.name, str(tileset_offset)
                        )
                        csvout.writerow([
                            layer.name, gid, '', '',
                            tileset.name, tileset_firstgid, tileset_offset,
                            tile['type'], tile['content']
                        ])
                        layer_tiles.add(gid)
            elif isinstance(layer, pytiled_parser.ObjectLayer):
                layer_mods = set()
                obj_idx = 0
                for obj in layer.tiled_objects:
                    if not hasattr(obj, 'gid'):
                        row = [
                            layer.name, '',
                            int(obj.coordinates.x / dungeon_part.tile_size.width),
                            int(obj.coordinates.y / dungeon_part.tile_size.height),
                            '', '', ''
                        ]
                        tiled_parse_mod(csvout, row, obj, layer_mods)\
                            or tiled_parse_monster(csvout, row, obj)\
                            or tiled_parse_npc(csvout, row, obj)\
                            or tiled_parse_stagehand(csvout, row, obj)\
                            or tiled_parse_vehicle(csvout, row, obj)
                    else:
                        gid = unflip_object(obj.gid)
                        tileset_idx = bisect_left(tileset_index['lastgids'], gid)
                        tileset = tileset_index['tilesets'][tileset_idx]
                        tileset_firstgid = tileset_index['firstgids'][tileset_idx]
                        tileset_offset = gid - tileset_firstgid
                        assert tileset_offset >= 0
                        assert tileset_offset < tileset.tile_count
                        tile = get_tile(
                            embedded_tilesets, external_tilesets,
                            tileset.name, str(tileset_offset)
                        )
                        row = [
                            layer.name, obj.gid,
                            int(obj.coordinates.x / dungeon_part.tile_size.width),
                            int(obj.coordinates.y / dungeon_part.tile_size.height),
                            tileset.name, tileset_firstgid, tileset_offset,
                            tile['type'], tile['content']
                        ]
                        if tile['type'] == 'object':
                            parameters = get_tiled_property(obj, 'parameters')
                            if parameters:
                                parameters = json.loads(parameters)
                                if 'spawner' in parameters:
                                    monsterTypes = parameters['spawner']\
                                        .get('monsterTypes')
                                    if not monsterTypes:
                                        raise Exception('Malformed spawner')
                                    row.append('monsterTypes={}'.format(';'\
                                        .join(monsterTypes)))
                                elif 'treasurePools' in parameters:
                                    row.append('treasurePools={}'.format(';'\
                                        .join(parameters['treasurePools'])))
                        csvout.writerow(row)
                    obj_idx += 1
            layer_idx += 1

    seen_tiled_parts.add(partpath / partfile)
