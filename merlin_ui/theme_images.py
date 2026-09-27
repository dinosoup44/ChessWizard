"""Tk image resources for the shared production board; no theme persistence."""
from collections import OrderedDict
import chess
from PIL import Image, ImageTk
from theme_core.board_geometry import PIECE_FRACTION, EMBLEM_OPACITY
from merlin_ui.piece_sets import UnicodePieceSet
from merlin_ui.appearance import DEFAULT_PIECE_STYLE

MAX_SCALED_IMAGES = 64


class ThemeImages:
    def __init__(self,master,loaded):
        self.master,self.loaded=master,loaded
        self.cache=OrderedDict()
        self.fallback=UnicodePieceSet(DEFAULT_PIECE_STYLE)

    def photo(self,kind,role,width,height,opacity=1):
        width,height=max(1,int(width)),max(1,int(height))
        key=(kind,role,width,height,opacity)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        asset=getattr(self.loaded,kind).get(role)
        if asset is None:return None
        image=asset.image()
        ratio=min(width/image.width,height/image.height)
        image=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.LANCZOS)
        if opacity!=1:
            image.putalpha(image.getchannel("A").point(lambda a:round(a*opacity)))
        photo=ImageTk.PhotoImage(image,master=self.master)
        self.cache[key]=photo
        while len(self.cache)>MAX_SCALED_IMAGES:self.cache.popitem(last=False)
        return photo

    def draw_piece(self,canvas,piece,center_x,center_y,square_size):
        role=("white_" if piece.color else "black_")+chess.piece_name(piece.piece_type)
        image=self.photo("pieces",role,square_size*PIECE_FRACTION,square_size*PIECE_FRACTION)
        if image is None:
            self.fallback.draw_piece(canvas,piece,center_x,center_y,square_size)
        else:
            canvas._image_refs.append(image)
            canvas.create_image(center_x,center_y,image=image,tags=("piece",role))

    def draw_decorations(self,canvas,geometry):
        for role,(x,y,w,h) in geometry.decoration_boxes().items():
            if w<1 or h<1:continue
            image=self.photo("decorations",role,w,h,EMBLEM_OPACITY if role=="center_emblem" else 1)
            if image is not None:
                canvas._image_refs.append(image)
                canvas.create_image(x+w/2,y+h/2,image=image,tags=("decoration",role))
