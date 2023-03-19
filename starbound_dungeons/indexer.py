from bisect import bisect_left
from json_minify import json_minify
from pathlib import Path
from PIL import Image

import argparse
import csv
import json
import os
import pytiled_parser
import re
import sys


# Exclude dungeons that are known to contain errors such that they are
# not able to be parsed.
path_excludes = ['other/cultistlair/old/*']

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

dst_dir = None
src_dir = None

# Some Tiled dungeon parts are referenced by multiple dungeons. Indexing
# them multiple times provides no benefit and takes time, so keep a list
# of which parts were already seen.
seen_tiled_parts = set()


def check_allowed_path(path):
    '''
    Determines if a given path contains forbidden subpaths.

    path is a Path object.

    Returns true if the path is allowed and false otherwise.
    '''
    for excluded in path_excludes:
        if path.match(excluded): return False
    return True


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
        if prev_tileset is None:
            prev_tileset = tileset
            continue
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


def make_dst_dir(partpath):
    '''
    Makes a destination directory corresponding to the given source
    directory. If the directory already exists, this is a no-op.

    partpath is a string containing the absolute path to the directory
    containing the part.

    Returns the absolute path to the destination directory.
    '''
    assert str(partpath).find(str(src_dir)) == 0
    assert len(str(partpath)) > len(str(src_dir))
    dst_relative_path = str(partpath)[len(str(src_dir)) + 1:]
    dst_path = dst_dir / dst_relative_path
    dst_path.mkdir(parents=True, exist_ok=True)
    return dst_path


def png_maybe_output(tile, seen, csvout, rows):
    if tile['record'] == 'always':
        for row in rows: csvout.writerow(row)
    elif tile['record'] == 'once' and tile['color'] not in seen:
        for row in rows: csvout.writerow(row)
        seen.add(tile['color'])


def to_brush_color(rgba):
    return "#{r:02x}{g:02x}{b:02x}{a:02x}".format(
        r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3])


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


class BrushParseError(Exception):
    def __init__(category, color):
        super(BrushParseError, self).__init__()
        self.category = category
        self.color = color

    def __repr__():
        return 'unknown tile brush ({}): {}'.format(category, color)


def brush_parse_treasurePools(out, brush):
    if len(brush) > 2 and isinstance(brush[2], dict):
        treasurePools = brush[2].get('parameters', {}).get('treasurePools', [])
        if treasurePools:
            out['treasurePools'] = 'treasurePools={}'\
                .format(';'.join(treasurePools))


def preprocess_brushes(dungeon):
    brushes = {}
    for tile in dungeon.get('tiles', []):
        value = tile['value']
        color = to_brush_color(value)

        brush = tile.get('brush')
        if not brush:
            brushes[color] = {
                'color': color,
                'type': tile.get('connector') and 'connector' or 'no-op',
                'record': 'never'
            }
        elif not isinstance(brush, list):
            raise BrushParseError("root", str(value))
        elif not brush[0] or not isinstance(brush[0], list):
            raise BrushParseError("root", str(value))
        elif brush[0][0] == 'clear' and len(brush) == 1:
            brushes[color] = {
                'color': color,
                'type': 'clear',
                'record': 'never'
            }
        elif brush[0][0] == 'clear' and len(brush) > 1:
            if not brush[1] or not isinstance(brush[1], list):
                raise BrushParseError("clear", str(value))
            elif brush[1][0] == 'object':
                brushes[color] = {
                    'color': color,
                    'type': 'object',
                    'object': brush[1][1],
                    'record': 'always'
                }
                brush_parse_treasurePools(brushes[color], brush[1])
                assert len(brush) == 2
            elif brush[1][0] == 'front':
                brushes[color] = {
                    'color': color,
                    'type': 'material',
                    'front': brush[1][1],
                    'record': 'once'
                }
                assert len(brush) == 2
            elif brush[1][0] == 'back':
                brushes[color] = {
                    'color': color,
                    'type': 'material',
                    'back': brush[1][1],
                    'record': 'once'
                }
                if len(brush) > 2:
                    if not brush[2] or not isinstance(brush[2], list):
                        raise BrushParseError("clear secondary", str(value))
                    elif brush[2][0] == 'front':
                        brushes[color]['front'] = brush[2][1]
                    elif brush[2][0] == 'object':
                        brushes[color]['object'] = brush[2][1]
                        brushes[color]['record'] = 'always'
                        brush_parse_treasurePools(brushes[color], brush[2])
                    else:
                        raise BrushParseError("clear secondary", str(value))
                    assert len(brush) == 3
            elif brush[1][0] == 'liquid':
                brushes[color] = {
                    'color': color,
                    'type': 'material',
                    'liquid': brush[1][1],
                    'record': 'once'
                }
                if len(brush) > 2:
                    if not brush[2] or not isinstance(brush[2], list):
                        raise BrushParseError("clear secondary", str(value))
                    elif brush[2][0] == 'object':
                        brushes[color]['object'] = brush[2][1]
                        brushes[color]['record'] = 'always'
                        brush_parse_treasurePools(brushes[color], brush[2])
                    else:
                        raise BrushParseError("clear secondary", str(value))
                    assert len(brush) == 3
            elif brush[1][0] == 'surfacebackground':
                brushes[color] = {
                    'color': color,
                    'type': 'material',
                    'back': 'metamaterial:{}'.format(brush[1][0]),
                    'record': 'never'
                }
                assert len(brush) == 2
            else:
                raise BrushParseError("clear", str(value))
        elif brush[0][0] == 'object':
            brushes[color] = {
                'color': color,
                'type': 'object',
                'object': brush[0][1],
                'record': 'always'
            }
            brush_parse_treasurePools(brushes[color], brush[0])
            assert len(brush) == 1
        elif brush[0][0] == 'back':
            brushes[color] = {
                'color': color,
                'type': 'material',
                'back': brush[0][1],
                'record': 'once'
            }
            if len(brush) > 1:
                if not brush[1] or not isinstance(brush[1], list):
                    raise BrushParseError("back secondary", str(value))
                elif brush[1][0] == 'front':
                    brushes[color][brush[1][0]] = brush[1][1]
                elif brush[1][0] == 'object':
                    brushes[color][brush[1][0]] = brush[1][1]
                    brushes[color]['record'] = 'always'
                    brush_parse_treasurePools(brushes[color], brush[1])
                else:
                    raise BrushParseError("back secondary", str(value))
                assert len(brush) == 2
        elif brush[0][0] == 'random':
            if len(brush[0]) != 2 or not isinstance(brush[0][1], list):
                raise BrushParseError("random", str(value))
            else:
                objects = []
                for item in brush[0][1]:
                    if len(item) > 1 and item[0] == 'object':
                        objects.append(item[1])
                    else:
                        raise BrushParseError("random secondary", str(value))
                brushes[color] = {
                    'color': color,
                    'type': 'object',
                    'object': ';'.join(objects),
                    'record': 'always'
                }
        elif brush[0][0] == 'npc':
            if brush[0][1]['kind'] == 'monster':
                brushes[color] = {
                    'color': color,
                    'type': 'monster',
                    'typeName': brush[0][1]['typeName'],
                    'record': 'always'
                }
            elif brush[0][1]['kind'] == 'npc':
                brushes[color] = {
                    'color': color,
                    'type': 'npc',
                    'typeName': brush[0][1]['typeName'],
                    'species': brush[0][1].get('species'),
                    'record': 'always'
                }
            else:
                raise BrushParseError("npc", str(value))
        elif brush[0][0] == 'stagehand':
            if brush[0][1]['type'] == 'questlocation':
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': brush[0][1]['type'],
                    'location': brush[0][1]['parameters']['locationType'],
                    'record': 'always'
                }
            elif brush[0][1]['type'] == 'radiomessage':
                radioMessage = brush[0][1]['parameters']\
                    .get('radioMessage', ';'.join(brush[0][1]['parameters']\
                    .get('radioMessages', [])))
                if not radioMessage:
                    raise BrushParseError("radiomessage", str(value))
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': brush[0][1]['type'],
                    'radioMessage': radioMessage,
                    'record': 'always'
                }
            elif brush[0][1]['type'] == 'objecttracker':
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': brush[0][1]['type'],
                    'record': 'never'
                }
            elif brush[0][1]['type'] == 'messenger':
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': brush[0][1]['type'],
                    'messageType': brush[0][1]['parameters']['messageType'],
                    'record': 'never'
                }
            elif brush[0][1]['type'] == 'bossmusic':
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': brush[0][1]['type'],
                    'uniqueId': brush[0][1]['parameters']['uniqueId'],
                    'record': 'never'
                }
            else:
                raise BrushParseError("stagehand", str(value))
        elif brush[0][0] == 'wire':
            brushes[color] = {
                'color': color,
                'type': 'wire',
                'record': 'never'
            }
        elif brush[0][0] == 'biometree':
            brushes[color] = {
                'color': color,
                'type': 'biometree',
                'record': 'never'
            }
            assert len(brush) == 1
        elif brush[0][0] == 'biomeitems':
            brushes[color] = {
                'color': color,
                'type': 'biomeitems',
                'record': 'never'
            }
            assert len(brush) == 1
        elif brush[0][0] == 'playerstart':
            brushes[color] = {
                'color': color,
                'type': 'playerstart',
                'record': 'never'
            }
            assert len(brush) == 1
        elif brush[0][0] == 'surface':
            brushes[color] = {
                'color': color,
                'type': 'material',
                'front': 'metamaterial:{}'.format(brush[0][0]),
                'record': 'never'
            }
            assert len(brush) == 1
        else:
            raise BrushParseError("root", str(value))
    return brushes


def brush_parse_ship_treasurePools(out, brush):
    p = brush.get('objectParameters', {}).get('treasurePools', [])
    if p: out['treasurePools'] = 'treasurePools={}'.format(';'.join(p))


def preprocess_ship_brushes(blockKey, key):
    brushes = {}
    for tile in blockKey[key]:
        value = tile['value']
        if len(value) == 3: value.append(255)
        color = to_brush_color(value)
        brushes[color] = {'color': color, 'type': 'no-op', 'record': 'never'}
        if not tile['backgroundBlock'] and not tile['foregroundBlock']:
            if tile.get('object'):
                brushes[color]['object'] = tile['object']
                brushes[color]['record'] = 'always'
                brushes[color]['type'] = 'object'
                brush_parse_ship_treasurePools(brushes[color], tile)
        elif tile['backgroundBlock']:
            brushes[color]['record'] = 'once'
            brushes[color]['type'] = 'material'
            if tile.get('backgroundMat'):
                brushes[color]['back'] = tile['backgroundMat']
            if tile['foregroundBlock'] and tile.get('foregroundMat'):
                assert not tile.get('object')
                brushes[color]['front'] = tile['foregroundMat']
            if tile.get('object'):
                assert not tile.get('foregroundMat')
                brushes[color]['object'] = tile['object']
                brushes[color]['record'] = 'always'
                brush_parse_ship_treasurePools(brushes[color], tile)
        else: # tile['foregroundBlock']
            brushes[color]['record'] = 'once'
            brushes[color]['type'] = 'material'
            if tile.get('foregroundMat'):
                assert not tile.get('object')
                brushes[color]['front'] = tile['foregroundMat']
    return brushes


def preprocess_tilesets():
    tilesets = {}

    tsdir = src_dir / 'tilesets'
    if not tsdir.is_dir():
        # These assets do not contain any tilesets. This will only
        # become an error if Tiled dungeons exist in these assets.
        return tilesets

    for relative_path in tsdir.glob('**/*.json'):
        tileset = None
        with open(tsdir / relative_path, 'rb') as fh:
            tileset = json.loads(fh.read())

        assert tilesets.get(tileset['name']) is None
        tilesets[tileset['name']] = {}
        for offset in tileset.get('tiles', {}).keys():
            tile = tileset.get('tileproperties', {})[offset]
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

    return tilesets


def index_png_dungeon_part(partpath, partfile, brushes):
    with Image.open(partpath / partfile) as dungeon_part:
        if dungeon_part.mode == 'P':
            dungeon_part = dungeon_part.convert('RGB')
        if dungeon_part.mode == 'RGB':
            dungeon_part.putalpha(255)

        width, height = dungeon_part.size

        dst_path = make_dst_dir(partpath)
        with open(dst_path / "{}.csv".format(partfile), 'w') as fh:
            csvout = csv.writer(fh, lineterminator='\n')

            seen_colors = set()
            for y in range(height):
                for x in range(width):
                    color = '#' + bytearray(dungeon_part.getpixel((x, y))).hex()
                    if len(color) != 9:
                        print('{}: unknown color format: {}'.format(
                            partpath / partfile, color), file=sys.stderr)
                        print('  mode = {}'.format(
                            dungeon_part.mode), file=sys.stderr)
                        sys.exit(1)
                    tile = brushes.get(color)
                    if not tile:
                        print('{}: unknown tile {}'.format(
                            partpath / partfile, color), file=sys.stderr)
                        print('  brushes = {}'.format(
                            str(brushes)), file=sys.stderr)
                        sys.exit(1)
                    if tile['type'] == 'material':
                        rows = []
                        if 'back' in tile:
                            rows.append([
                                'back', color, '', '', '', '', '',
                                'material', tile['back']
                            ])
                        if 'front' in tile:
                            rows.append([
                                'front', color, '', '', '', '', '',
                                'material', tile['front']
                            ])
                        if 'liquid' in tile:
                            rows.append([
                                'front', color, '', '', '', '', '',
                                'liquid', tile['liquid']
                            ])
                        if 'object' in tile:
                            obj = [
                                'objects', color, x, y, '', '', '',
                                'object', tile['object']
                            ]
                            if tile.get('treasurePools'):
                                obj.append(tile['treasurePools'])
                            rows.append(obj)
                        png_maybe_output(tile, seen_colors, csvout, rows)
                    elif tile['type'] == 'monster':
                        png_maybe_output(tile, seen_colors, csvout, [[
                            'monsters & npcs', color, x, y, '', '', '',
                            'monster', tile['typeName']
                        ]])
                    elif tile['type'] == 'npc':
                        png_maybe_output(tile, seen_colors, csvout, [[
                            'monsters & npcs', color, x, y, '', '', '',
                            'npc', tile['typeName'],
                            'species={}'.format(tile['species'])
                        ]])
                    elif tile['type'] == 'object':
                        obj = [
                            'objects', color, x, y, '', '', '',
                            'object', tile['object']
                        ]
                        if tile.get('treasurePools'):
                            obj.append(tile['treasurePools'])
                        png_maybe_output(tile, seen_colors, csvout, [obj])
                    elif tile['type'] == 'stagehand':
                        if tile['typeName'] == 'questlocation':
                            png_maybe_output(tile, seen_colors, csvout, [[
                                'mods', color, x, y, '', '', '',
                                'stagehand', 'questlocation',
                                'location={}'.format(tile['location'])
                            ]])
                        elif tile['typeName'] == 'radiomessage':
                            png_maybe_output(tile, seen_colors, csvout, [[
                                'mods', color, x, y, '', '', '',
                                'stagehand', 'radiomessage',
                                'message={}'.format(tile['radioMessage'])
                            ]])


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
        print('Ignored stagehand type: {}'.format(stagehandType),
              file=sys.stderr)
        return True


def tiled_parse_vehicle(csvout, partialRow, obj):
    vehicleType = get_tiled_property(obj, 'vehicle')
    if vehicleType:
        row = partialRow.copy()
        row.extend(['vehicle', vehicleType])
        csvout.writerow(row)
        return True


def index_tiled_dungeon_part(partpath, partfile, all_tilesets):
    if partpath / partfile in seen_tiled_parts: return

    dst_path = make_dst_dir(partpath)

    dungeon_part = pytiled_parser.parse_map(partpath / partfile)
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
                        tile = all_tilesets[tileset.name][str(tileset_offset)]
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
                        tile = all_tilesets[tileset.name][str(tileset_offset)]
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


def index_all_dungeons():
    ddir = src_dir / 'dungeons'
    if not ddir.is_dir():
        # These assets do not contain any dungeon files.
        return

    all_tilesets = preprocess_tilesets()
    for relative_path in ddir.glob('**/*.dungeon'):
        if not check_allowed_path(relative_path): continue

        full_dungeon_path = ddir / relative_path
        full_dungeon_dir = full_dungeon_path.parent
        dungeon = None
        print(full_dungeon_path)
        with open(full_dungeon_path, 'rb') as fh:
            # json_minify is incredibly slow. Invoking it only in cases
            # in which the JSON contains comments provides a significant
            # performance improvement.
            try:
                dungeon = json.loads(fh.read())
            except json.decoder.JSONDecodeError as e:
                fh.seek(0)
                dungeon = json.loads(json_minify(fh.read().decode('utf-8')))

        brushes = None
        try:
            brushes = preprocess_brushes(dungeon)
        except BrushParseError as e:
            print('{}: {}'.format(full_dungeon_path, str(e)), file=sys.stderr)
            sys.exit(1)

        for part in dungeon.get('parts', []):
            partdef = part.get('def', [])
            if len(partdef) > 1:
                if partdef[0] == 'tmx':
                    partfile = partdef[1]
                    if isinstance(partfile, list):
                        partfile = partfile[0]
                    partpath = full_dungeon_dir
                    if partfile[0] == '/':
                        partpath = src_dir / os.path.dirname(partfile)[1:]
                        partfile = os.path.basename(partfile)
                    assert partfile == os.path.basename(partfile)
                    print(partpath / partfile)
                    index_tiled_dungeon_part(partpath, partfile, all_tilesets)
                elif partdef[0] == 'image':
                    for partfile in partdef[1]:
                        partpath = full_dungeon_dir
                        if partfile[0] == '/':
                            partpath = src_dir / os.path.dirname(partfile)[1:]
                            partfile = os.path.basename(partfile)
                        assert partfile == os.path.basename(partfile)
                        print(partpath / partfile)
                        index_png_dungeon_part(partpath, partfile, brushes)


def index_all_ships():
    sdir = src_dir / 'ships'
    if not sdir.is_dir():
        # These assets do not contain any ship files.
        return

    blockKeys = {}
    for relative_path in sdir.glob('**/*.structure'):
        full_dungeon_path = sdir / relative_path
        full_dungeon_dir = full_dungeon_path.parent
        dungeon = None
        print(full_dungeon_path)
        with open(full_dungeon_path, 'rb') as fh:
            # See above comments on json_minify.
            try:
                dungeon = json.loads(fh.read())
            except json.decoder.JSONDecodeError as e:
                fh.seek(0)
                dungeon = json.loads(json_minify(fh.read().decode('utf-8')))

        blockKeyFilename, blockKeyKey = dungeon['blockKey'].split(':')
        full_blockKey_path = full_dungeon_dir / blockKeyFilename
        if blockKeyFilename[0] == '/':
            full_blockKey_path = src_dir / blockKeyFilename[1:]
        blockKey = blockKeys.get(full_blockKey_path)
        if not blockKey:
            print(full_blockKey_path)
            with open(full_blockKey_path, 'rb') as fh:
                # See above comments on json_minify.
                try:
                    blockKey = json.loads(fh.read())
                except json.decoder.JSONDecodeError as e:
                    fh.seek(0)
                    blockKey = json.loads(json_minify(fh.read()\
                        .decode('utf-8')))
            blockKeys[full_blockKey_path] = blockKey

        brushes = preprocess_ship_brushes(blockKey, blockKeyKey)

        partpath = full_dungeon_dir
        partfile = dungeon['blockImage']
        if partfile[0] == '/':
            partpath = src_dir / os.path.dirname(partfile)[1:]
            partfile = os.path.basename(partfile)
        assert partfile == os.path.basename(partfile)
        print(partpath / partfile)
        index_png_dungeon_part(partpath, partfile, brushes)


def main():
    parser = argparse.ArgumentParser(
        description="Index the resources used in Starbound dungeons."
    )
    parser.add_argument(
        '-d', '--dst', required=True,
        help='the folder in which to write the indices'
    )
    parser.add_argument(
        '-s', '--src', required=True,
        help='the folder containing the unpacked assets'
    )
    args = parser.parse_args()

    global dst_dir
    dst_dir = Path(args.dst)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_dir = dst_dir.resolve(strict=True)

    global src_dir
    src_dir = Path(args.src).resolve(strict=True)

    if dst_dir.samefile(src_dir)\
       or dst_dir.is_relative_to(src_dir)\
       or src_dir.is_relative_to(dst_dir):
        print('error: destination and source folders must be independent',
              file=sys.stderr)
        sys.exit(1)

    if not (src_dir / '_metadata').is_file():
        print('error: source folder does not contain Starbound assets',
              file=sys.stderr)
        sys.exit(1)

    index_all_dungeons()
    index_all_ships()
