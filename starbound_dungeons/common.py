def make_dst_dir(src_dir, dst_dir, partpath):
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
