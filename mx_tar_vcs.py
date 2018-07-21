import time


class TarVC(object):
    """ Proof of concept for building from a tarball. """

    def check(self, abortOnError=True):
        return self

    def root(self, directory, abortOnError=True):
        # TODO: figure out how to do this without hard coding. Some meta data?
        if directory.endswith("/compiler"):
            return directory[:-len("/compiler")]
        if directory.endswith("/truffle"):
            return directory[:-len("/truffle")]
        if directory.endswith("/tools"):
            return directory[:-len("/tools")]
        if directory.endswith("/sdk"):
            return directory[:-len("/sdk")]

        return directory

    def release_version_from_tags(self, vcdir, prefix, snapshotSuffix='dev', abortOnError=True):
        return None

    def parent(self, vcdir, abortOnError=True):
        return 'unknown-{0}'.format(time.strftime('%Y-%m-%d_%H-%M-%S_%Z'))
