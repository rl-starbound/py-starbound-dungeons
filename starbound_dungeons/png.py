from .common import make_dst_dir

from PIL import Image

import csv
import sys


class BrushParseError(Exception):
    def __init__(category, color):
        super(BrushParseError, self).__init__()
        self.category = category
        self.color = color

    def __repr__():
        return 'unknown tile brush ({}): {}'.format(category, color)


def png_maybe_output(tile, seen, csvout, rows):
    if tile['record'] == 'always':
        for row in rows: csvout.writerow(row)
    elif tile['record'] == 'once' and tile['color'] not in seen:
        for row in rows: csvout.writerow(row)
        seen.add(tile['color'])


def to_brush_color(rgba):
    return "#{r:02x}{g:02x}{b:02x}{a:02x}".format(
        r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3])


def brush_parse_treasurePools(out, brush):
    if len(brush) > 2 and isinstance(brush[2], dict):
        treasurePools = brush[2].get('parameters', {}).get('treasurePools', [])
        if treasurePools:
            out['treasurePools'] = 'treasurePools={}'\
                .format(';'.join(treasurePools))


def process_brushes(dungeon):
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
            # BETA
            elif brush[1][0] in [
                'acid', 'lava', 'tarliquid', 'tentaclejuice', 'water'
            ]:
                brushes[color] = {
                    'color': color,
                    'type': 'material',
                    'liquid': brush[1][0],
                    'record': 'once'
                }
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
            # BETA - This is equivalent to a radiomessage.
            elif brush[0][1]['type'] == 'aimessage':
                aiMessage = brush[0][1]['parameters']['broadcastAction']['id']
                brushes[color] = {
                    'color': color,
                    'type': 'stagehand',
                    'typeName': 'radiomessage',
                    'radioMessage': aiMessage,
                    'record': 'always'
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


def process_ship_brushes(blockKey):
    brushes = {}
    for tile in blockKey:
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


def index_png_dungeon_part(src_dir, dst_dir, partpath, partfile, brushes):
    try:
        with Image.open(partpath / partfile) as dungeon_part:
            _index_png_dungeon_part(
                src_dir, dst_dir, partpath, partfile, brushes, dungeon_part
            )
    except FileNotFoundError as e:
        # BETA - incorrect file case.
        partfile = partfile.lower()
        with Image.open(partpath / partfile) as dungeon_part:
            _index_png_dungeon_part(
                src_dir, dst_dir, partpath, partfile, brushes, dungeon_part
            )


def _index_png_dungeon_part(
    src_dir, dst_dir, partpath, partfile, brushes, dungeon_part
):
    if dungeon_part.mode == 'P':
        dungeon_part = dungeon_part.convert('RGB')
    if dungeon_part.mode == 'RGB':
        dungeon_part.putalpha(255)

    width, height = dungeon_part.size

    dst_path = make_dst_dir(src_dir, dst_dir, partpath)
    with open(dst_path / "{}.csv".format(partfile), 'w') as fh:
        csvout = csv.writer(fh, lineterminator='\n')

        seen_colors = set()
        seen_error_colors = set()
        for y in range(height):
            for x in range(width):
                color = '#' + bytearray(dungeon_part.getpixel((x, y))).hex()
                if len(color) != 9:
                    print('ERROR: unknown color format: {} mode: {}'.format(
                        color, dungeon_part.mode))
                    sys.exit(1)
                tile = brushes.get(color)
                if not tile:
                    if color not in seen_error_colors:
                        print('WARNING: unknown tile {}'.format(color))
                        seen_error_colors.add(color)
                    continue
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
