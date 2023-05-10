import contextlib
import weakref

from ._block.key import Key as BlockKey
from ._block.options import Options as BlockOptions
from ._helpers import validate_version
from .extension import ExtensionProxy


class SerializationContext:
    """
    Container for parameters of the current (de)serialization.
    """

    def __init__(self, version, extension_manager, url, blocks):
        self._version = validate_version(version)
        self._extension_manager = extension_manager
        self._url = url
        self._blocks = blocks

        self.__extensions_used = set()

    @property
    def url(self):
        """
        The URL (if any) of the file being read or written.

        Used to compute relative locations of external files referenced by this
        ASDF file. The URL will not exist in some cases (e.g. when the file is
        written to an `io.BytesIO`).

        Returns
        --------
        str or None
        """
        return self._url

    @property
    def version(self):
        """
        Get the ASDF Standard version.

        Returns
        -------
        str
        """
        return self._version

    @property
    def extension_manager(self):
        """
        Get the ExtensionManager for enabled extensions.

        Returns
        -------
        asdf.extension.ExtensionManager
        """
        return self._extension_manager

    def _mark_extension_used(self, extension):
        """
        Note that an extension was used when reading or writing the file.

        Parameters
        ----------
        extension : asdf.extension.Extension
        """
        self.__extensions_used.add(ExtensionProxy.maybe_wrap(extension))

    @property
    def _extensions_used(self):
        """
        Get the set of extensions that were used when reading or writing the file.

        Returns
        -------
        set of asdf.extension.Extension
        """
        return self.__extensions_used

    def get_block_data_callback(self, index, key=None):
        """
        Generate a callable that when called will read data
        from a block at the provided index

        Parameters
        ----------
        index : int
            Block index

        key : BlockKey
            TODO

        Returns
        -------
        callback : callable
            A callable that when called (with no arguments) returns
            the block data as a one dimensional array of uint8
        """
        raise NotImplementedError("abstract")

    def find_available_block_index(self, data_callback, lookup_key=None):
        """
        Find the index of an available block to write data.

        This is typically used inside asdf.extension.Converter.to_yaml_tree

        Parameters
        ----------
        data_callback: callable
            Callable that when called will return data (ndarray) that will
            be written to a block.
            At the moment, this is only assigned if a new block
            is created to avoid circular references during AsdfFile.update.

        lookup_key : hashable, optional
            Unique key used to retrieve the index of a block that was
            previously allocated or reserved. For ndarrays this is
            typically the id of the base ndarray.

        Returns
        -------
        block_index: int
            Index of the block where data returned from data_callback
            will be written.
        """
        raise NotImplementedError("abstract")

    def generate_block_key(self):
        raise NotImplementedError("abstract")

    @contextlib.contextmanager
    def _serialization(self, obj):
        with _Serialization(self, obj) as op:
            yield op

    @contextlib.contextmanager
    def _deserialization(self):
        with _Deserialization(self) as op:
            yield op


class _Operation(SerializationContext):
    def __init__(self, ctx):
        self._ctx = weakref.ref(ctx)
        super().__init__(ctx.version, ctx.extension_manager, ctx.url, ctx._blocks)

    def _mark_extension_used(self, extension):
        ctx = self._ctx()
        ctx._mark_extension_used(extension)

    @property
    def _extensions_used(self):
        ctx = self._ctx()
        return ctx._extensions_used

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class _Deserialization(_Operation):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._obj = None
        self._blk = None
        self._cb = None
        self._keys = set()

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            return
        if self._blk is not None:
            self._blocks.blocks.assign_object(self._obj, self._blk)
            self._blocks._data_callbacks.assign_object(self._obj, self._cb)
        for k in self._keys:
            k.assign_object(self._obj)

    def get_block_data_callback(self, index, key=None):
        blk = self._blocks.blocks[index]
        cb = self._blocks._get_data_callback(index)

        if key is None:
            if self._blk is not None:
                msg = "Converters accessing >1 block must provide a key for each block"
                raise OSError(msg)
            self._blk = blk
            self._cb = cb
        else:
            self._blocks.blocks.assign_object(key, blk)
            self._blocks._data_callbacks.assign_object(key, cb)

        return cb

    def generate_block_key(self):
        key = BlockKey()
        self._keys.add(key)
        return key


class _Serialization(_Operation):
    def __init__(self, ctx, obj):
        super().__init__(ctx)
        self._obj = obj

    def find_available_block_index(self, data_callback, lookup_key=None):
        if lookup_key is None:
            lookup_key = self._obj
        return self._blocks.make_write_block(data_callback, BlockOptions(), lookup_key)

    def generate_block_key(self):
        return BlockKey(self._obj)


class _IgnoreBlocks(_Operation):
    pass
