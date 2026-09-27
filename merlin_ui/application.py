"""Desktop-only navigation over existing views and shared services."""
import tkinter as tk
from merlin_ui.game_review_view import GameReviewView
from merlin_ui.startup import prepare_database


class ChessWizardApplication:
    """One profile and runtime; child views retain their existing lifecycle."""
    def __init__(self, root, database_path):
        self.root = root
        self.database_path = database_path
        self.review = GameReviewView(root, database_path=database_path)
        from merlin_ui.application_menu import application_menu
        self.menu = application_menu(root, review=self.review, shell=self.review.shell, close=self.close,
            last_move_var=self.review.show_last_move_var, toggle_last_move=self.review.toggle_last_move,
            open_training=self.open_training, open_review=root.lift)
        root.protocol("WM_DELETE_WINDOW", self.close)

    @property
    def training(self):
        return self.review.training

    @training.setter
    def training(self, value):
        self.review.training = value

    def open_training(self):
        return self.review.open_training()

    def close(self):
        self.review.close()


def main():
    root = tk.Tk()
    path = prepare_database(root)
    if path is not None:
        application = ChessWizardApplication(root, path)
        root.mainloop()
