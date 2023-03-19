# py-starbound-dungeons

This package provides a utility to parse
[Starbound](https://playstarbound.com/) dungeon files and index the
materials and objects used within them. It is able to accurately parse
both PNG and [Tiled](https://www.mapeditor.org/) dungeons.

## Installation

The easiest way to install is to use pip:

```
pip install py-starbound-dungeons
```

The source can be found at:
https://github.com/rl-starbound/py-starbound-dungeons

## Index Generation

The utility provided by this package operates under the assumption that
the user has extracted the game's assets from its `.pak` files. Doing so
is left as an exercise for the user.

To generate indices, run the command, giving it source and destination
folders:

```
pystarbound-dungeons-indexer -s assets -d indices
```

where `assets` is the path to the unpacked assets folder and `indices`
is the path to the folder to which the indices will be written. The
program will create `indices` if it does not exist, and will overwrite
any indices that already exist under `indices`.

On the author's laptop, the process of indexing all of the Starbound
base assets takes about 35 minutes. It needs to be re-run only if the
indexed assets change, e.g., after a new release of Starbound.

### Indexing Mod Assets

In Starbound, mods are applied as an overlay virtual file system, with
the base assets (usually) forming the lowest layer, and mod assets
layered on top, either overwriting or patching lower-ranked assets. The
indexer provided in this package can be used to index mod dungeon parts
as well as those of the base game, however, users should be aware that
it does not attempt to replicate the complexity of the Starbound mod
overlay system, resulting in important limitations:
* It indexes only one mod at a time.
* It does not attempt to apply patches. It indexes only PNG and Tiled
  JSON dungeon parts.
* For Tiled dungeon parts, it requires all referenced tilesets to exist
  in the correct locations relative to the dungeon parts. In practice,
  this usually means that the base game's tilesets must be symbolically
  linked into the mod's `tilesets` folder prior to running the indexer.
  How to do this varies based on the user's operating system, and is
  left as an exercise for the user.

It is highly recommended to use a separate destination folder for each
mod, as well as for the base game assets. The following is a recommended
destination folder structure for indexes for the base game and mods:

```
${HOME}/
  starbound-indices/
    base-game/
    mod1/
    mod2/
    ...
```

## Index Format

Indices are written in comma-separated values files with the following
columns:
* `layer`
* for PNG files: RGBA `color`; for Tiled files: `gid` or blank
* `x-axis coordinate` (non-material/mod tiles only)
* `y-axis coordinate` (non-material/mod tiles only)
* `tileset name` (Tiled materials and objects only)
* `tileset first gid` (Tiled materials and objects only)
* `tileset offset` (Tiled materials and objects only)
* `entity type`
* `entity name`
* optional modifier(s)

The primary purpose of this program is to index "interesting" entities
that appear in dungeon parts, such as materials, liquids, objects,
material mods, monsters, NPCs, vehicles, and some stagehands. The author
has chosen not to index "uninteresting" entities such as wiring,
anchors, connectors, and most stagehands. In general, "interesting"
entities as those for which a user would likely wish to search by name.

### Index Format Notes

In PNG dungeon parts, multiple entities may be recorded as having the
same `color`. This is because some PNG colors are declared in the
`.dungeon` files to represent a combination of background layer and
foreground layer or object, or a combination of liquid and object.

In PNG dungeon parts, materials and liquids are recorded only once per
`color`, regardless of how many times that color appears in the part.
Likewise, in Tiled dungeon parts, materials, liquids, and mods are
recorded only once per `layer` in which they appear. In both cases, this
is done to avoid exploding the indices with millions of rows of the same
entities.

PNG dungeons do not contain layers in the same sense that Tiled dungeons
do. For the `layer` field in PNG dungeon parts, layer names have been
assigned contextually, based on the layer in which a similar entity in a
Tiled dungeon would be placed.

In Tiled dungeon parts, if `gid` is blank, the three tileset fields will
also be blank, and vice versa. In most cases in Tiled dungeon parts,
when `gid` is not blank, it will be equal to `tileset first gid +
tileset offset`. Cases in which this equality does not hold indicate
that the object's image is flipped horizontally in the Tiled dungeon
part.

## Index Search

Indices will be written using the same folder structure as the dungeon
files, with one index per dungeon part file. Users can simply open and
read the indices. However, use a of text search tool, such as the Unix
`grep` tool, will allow fast searching for specific entities.

Note that, in all given examples, it is assumed that the user uses the
`cd` command to enter the top-level folder of the index before entering
search commands.

A simple search for any match of microwave in any part of any index:

```
grep -Hr microwave .
```

A search for any object beginning with the word microwave:

```
grep -Hr ,object,microwave .
```

Advanced text search features can be used to narrowly target searches.
For example, grep has extensive support for regular expression pattern
matching. For example, to find any type of material that contains the
word fence.

```
grep -Hr ',material,[^,]*fence[^,]*$' .
```
