"""Shared display geometry; decoration presence never participates in layout."""
from dataclasses import dataclass
import chess

FRAME_FRACTION = 0.08
EMBLEM_FRACTION = 0.4
EMBLEM_OPACITY = 0.12
PIECE_FRACTION = 0.82


@dataclass(frozen=True)
class BoardGeometry:
    x: float
    y: float
    size: float
    frame: float = 0

    @classmethod
    def fit(cls,width,height,*,framed=False):
        side=max(0,min(width,height))
        margin=side*FRAME_FRACTION if framed else 0
        return cls((width-side)/2+margin,(height-side)/2+margin,side-2*margin,margin)

    @property
    def square_size(self):return self.size/8

    def square_xy(self,square,orientation=chess.WHITE):
        file,rank=chess.square_file(square),chess.square_rank(square)
        col,row=(file,7-rank) if orientation else (7-file,rank)
        return self.x+col*self.square_size,self.y+row*self.square_size

    def square_at(self,x,y,orientation=chess.WHITE):
        if not (self.size>0 and self.x<=x<self.x+self.size and self.y<=y<self.y+self.size):return None
        col,row=int((x-self.x)/self.square_size),int((y-self.y)/self.square_size)
        return chess.square(col,7-row) if orientation else chess.square(7-col,row)

    def decoration_boxes(self):
        x,y,s,m=self.x,self.y,self.size,self.frame
        e=s*EMBLEM_FRACTION
        return dict(corner_top_left=(x-m,y-m,m,m),corner_top_right=(x+s,y-m,m,m),
                    corner_bottom_left=(x-m,y+s,m,m),corner_bottom_right=(x+s,y+s,m,m),
                    border_top=(x,y-m,s,m),border_bottom=(x,y+s,s,m),
                    border_left=(x-m,y,m,s),border_right=(x+s,y,m,s),
                    center_emblem=(x+(s-e)/2,y+(s-e)/2,e,e))
