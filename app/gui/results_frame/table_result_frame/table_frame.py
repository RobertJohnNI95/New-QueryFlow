from typing import Any, Tuple, Optional, Dict
import customtkinter as ctk
from pandas import DataFrame

from app.gui.results_frame.table_result_frame.table_widget import TableWidget
from app.gui.results_frame.table_result_frame.visualization import visualize
from app.gui.results_frame.table_result_frame.map_visualization import MapVisualizationWindow


class TableResultFrame(ctk.CTkFrame):
    def __init__(
        self,
        master: Any,
        width: int = 200,
        height: int = 200,
        corner_radius: int | str | None = None,
        border_width: int | str | None = None,
        bg_color: str | Tuple[str, str] = "transparent",
        fg_color: str | Tuple[str, str] | None = None,
        border_color: str | Tuple[str, str] | None = None,
        background_corner_colors: Tuple[str | Tuple[str, str]] | None = None,
        overwrite_preferred_drawing_method: str | None = None,
        **kwargs
    ):
        super().__init__(
            master,
            width,
            height,
            corner_radius,
            border_width,
            bg_color,
            fg_color,
            border_color,
            background_corner_colors,
            overwrite_preferred_drawing_method,
            **kwargs
        )

        self.label = ctk.CTkLabel(
            self,
            text="Table",
        )
        self.table = TableWidget(self)
        
        # Button frame for visualization buttons
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        # Add "Show Visualization" button
        self.visualize_button = ctk.CTkButton(
            self.button_frame,
            text="Show Visualization",
            command=lambda: visualize(self, self.get_table()),
            width=150,
        )
        
        # Add "Show on Map" button with enhanced styling
        self.map_button = ctk.CTkButton(
            self.button_frame,
            text="Show on Map",
            command=self.show_map,
            width=150,
            fg_color="#2B7A0B",
            hover_color="#1f5a08"
        )
        
        # Store GEE metadata
        self.gee_metadata: Optional[Dict] = None
        
        self.table_theme = ""
        self.label.pack(pady=5)
        self.table.pack(fill="both", expand=True, padx=5)
        self.table.pack_propagate(False)
        
        # Pack buttons side by side
        self.button_frame.pack(pady=5)
        self.visualize_button.pack(side="left", padx=5)
        self.map_button.pack(side="left", padx=5)
        
        if ctk.get_appearance_mode().lower() == "dark":
            self.change_table_theme("dark")
        else:
            self.table_theme = "light"

    def set_table(self, data_frame: DataFrame) -> None:
        self.table.set_data(data_frame)

    def get_table(self) -> DataFrame:
        return self.table.data

    def clear_table(self) -> None:
        self.table.reset_data()
        # Clear GEE metadata when table is cleared
        self.gee_metadata = None

    def set_gee_metadata(self, metadata: Optional[Dict]) -> None:
        """Store Google Earth Engine query metadata"""
        self.gee_metadata = metadata
    
    def show_map(self):
        """Open enhanced map visualization window with data"""
        # Pass both metadata and actual data to the map window
        MapVisualizationWindow(self, self.gee_metadata, self.get_table())

    def change_table_theme(self, theme: str) -> None:
        self.table_theme = theme
        self.table.sheet.change_theme(theme.lower() + " blue")