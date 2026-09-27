"""Bounded PNG decoding and canonicalization; imported content is never executed."""
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import stat
import warnings
from PIL import Image, UnidentifiedImageError

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_DIMENSION = 2048
MAX_PIXELS = MAX_DIMENSION * MAX_DIMENSION
MAX_THEME_BYTES = 64 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def reject_links(path: Path):
    """Reject symlinks and Windows reparse points, including ancestor junctions."""
    path=Path(path).absolute()
    for part in (path,*path.parents):
        if part.is_symlink():
            raise ValueError("Linked assets/directories are not supported")
        if part.exists():
            info=part.lstat()
            if getattr(info,"st_file_attributes",0) & getattr(stat,"FILE_ATTRIBUTE_REPARSE_POINT",0x400):
                raise ValueError("Reparse points are not supported")


@dataclass(frozen=True)
class PngAsset:
    data: bytes
    width: int
    height: int
    transparent: bool

    def image(self):
        with Image.open(BytesIO(self.data)) as image:
            return image.convert("RGBA")


def decode_png(data: bytes) -> PngAsset:
    if len(data)>MAX_FILE_BYTES or not data.startswith(PNG_SIGNATURE):
        raise ValueError("Use a PNG no larger than 8 MiB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error",Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format!="PNG" or getattr(source,"n_frames",1)!=1:
                    raise ValueError("Only static PNG images are supported")
                w,h=source.size
                if not (0<w<=MAX_DIMENSION and 0<h<=MAX_DIMENSION and w*h<=MAX_PIXELS):
                    raise ValueError("PNG dimensions must be at most 2048 × 2048")
                source.verify()
            with Image.open(BytesIO(data)) as source:
                image=source.convert("RGBA")
                image.load()
        output=BytesIO()
        image.save(output,format="PNG")
        canonical=output.getvalue()
        if len(canonical)>MAX_FILE_BYTES:
            raise ValueError("Decoded PNG exceeds the asset size limit")
        return PngAsset(canonical,w,h,image.getchannel("A").getextrema()[0]<255)
    except (OSError,SyntaxError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
        raise ValueError("Invalid or unsafe PNG image") from error


def load_png(path) -> PngAsset:
    path=Path(path)
    reject_links(path)
    if path.suffix.lower()!=".png" or not path.is_file():
        raise ValueError("Choose a regular PNG file; scripts and archives are not supported")
    with path.open("rb") as stream:
        return decode_png(stream.read(MAX_FILE_BYTES+1))
