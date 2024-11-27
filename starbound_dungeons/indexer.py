from .png import BrushParseError, index_png_dungeon_part, process_brushes, \
                 process_ship_brushes
from .tiled import index_tiled_dungeon_part, process_external_tilesets

from json_minify import json_minify
from pathlib import Path

import argparse
import json
import os
import sys


# Exclude dungeons that are known to contain errors such that they are
# not able to be parsed.
path_excludes = ['other/cultistlair/old/*']


def check_allowed_path(path):
    '''
    Determines if a given path contains forbidden subpaths.

    path is a Path object.

    Returns true if the path is allowed and false otherwise.
    '''
    for excluded in path_excludes:
        if path.match(excluded): return False
    return True


def index_all_dungeons(src_dir, dst_dir):
    ddir = src_dir / 'dungeons'
    if not ddir.is_dir():
        # These assets do not contain any dungeon files.
        return

    external_tilesets = process_external_tilesets(src_dir)
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
            brushes = process_brushes(dungeon)
        except BrushParseError as e:
            print('ERROR: invalid brush: {}'.format(full_dungeon_path, str(e)))
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
                    index_tiled_dungeon_part(
                        src_dir, dst_dir, partpath, partfile, external_tilesets
                    )
                elif partdef[0] == 'image':
                    for partfile in partdef[1]:
                        partpath = full_dungeon_dir
                        if partfile[0] == '/':
                            partpath = src_dir / os.path.dirname(partfile)[1:]
                            partfile = os.path.basename(partfile)
                        assert partfile == os.path.basename(partfile)
                        print(partpath / partfile)
                        index_png_dungeon_part(
                            src_dir, dst_dir, partpath, partfile, brushes
                        )


def extract_blockKey(
    full_dungeon_dir, src_dir, blockKeys, blockKeyFilename, blockKeyKey
):
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
                blockKey = json.loads(json_minify(fh.read().decode('utf-8')))
            blockKey = blockKey[blockKeyKey]
        blockKeys[full_blockKey_path] = blockKey
    return blockKey


def index_all_ships(src_dir, dst_dir):
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

        blockKey = None
        if isinstance(dungeon['blockKey'], str):
            blockKeyFilename, blockKeyKey = dungeon['blockKey'].split(':')
            try:
                blockKey = extract_blockKey(
                    full_dungeon_dir, src_dir,
                    blockKeys, blockKeyFilename, blockKeyKey
                )
            except FileNotFoundError as e:
                # BETA - incorrect file case.
                blockKeyFilename = blockKeyFilename.lower()
                blockKey = extract_blockKey(
                    full_dungeon_dir, src_dir,
                    blockKeys, blockKeyFilename, blockKeyKey
                )
        elif isinstance(dungeon['blockKey'], list):
            # BETA
            blockKey = dungeon['blockKey']
        else:
            print('ERROR: unknown blockKey format')
            sys.exit(1)

        brushes = process_ship_brushes(blockKey)

        partpath = full_dungeon_dir
        partfile = dungeon['blockImage']
        if partfile[0] == '/':
            partpath = src_dir / os.path.dirname(partfile)[1:]
            partfile = os.path.basename(partfile)
        assert partfile == os.path.basename(partfile)
        print(partpath / partfile)
        index_png_dungeon_part(src_dir, dst_dir, partpath, partfile, brushes)


def main():
    parser = argparse.ArgumentParser(
        description="Index the resources used in Starbound dungeons."
    )
    parser.add_argument(
        '-d', '--dst', required=True,
        help='the folder in which to write the indices'
    )
    parser.add_argument(
        '-f', '--force', action='store_true',
        help='force parsing if _metadata not found'
    )
    parser.add_argument(
        '-s', '--src', required=True,
        help='the folder containing the unpacked assets'
    )
    args = parser.parse_args()

    dst_dir = Path(args.dst)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_dir = dst_dir.resolve(strict=True)

    src_dir = Path(args.src).resolve(strict=True)

    if dst_dir.samefile(src_dir)\
       or dst_dir.is_relative_to(src_dir)\
       or src_dir.is_relative_to(dst_dir):
        print('ERROR: destination and source folders must be independent',
              file=sys.stderr)
        sys.exit(1)

    if not args.force and not (src_dir / '_metadata').is_file():
        print('ERROR: source folder does not contain Starbound assets',
              file=sys.stderr)
        sys.exit(1)

    index_all_dungeons(src_dir, dst_dir)
    index_all_ships(src_dir, dst_dir)
