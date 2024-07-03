from typing import List

import napari
import numpy as np
from magicgui import magicgui
from membrain_seg.segmentation.dataloading.data_utils import store_tomogram
from napari.layers.shapes._shapes_constants import Mode
from napari.layers.shapes._shapes_mouse_bindings import add_path_polygon_lasso
from napari.utils.colormaps import colormap
from qtpy.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from scipy.ndimage import label

from lasso_3d.lasso_add_slices import mask_via_extension
from lasso_3d.shapes_overwrites import redefine_shapelayer_functions


class Lasso3D(QWidget):
    def __init__(self, viewer: "napari.viewer.Viewer"):
        super().__init__()
        self.viewer = viewer

        self.annotation_box = QHBoxLayout()
        btn_freehand = QPushButton("Freehand")
        btn_freehand.clicked.connect(self._on_click_freehand)
        btn_points = QPushButton("Points")
        btn_points.clicked.connect(self._on_click_polygon)
        self.annotation_box.addWidget(btn_freehand)
        self.annotation_box.addWidget(btn_points)

        self.selection_box = QHBoxLayout()
        self._layer_selection_widget = magicgui(
            self._lasso_from_polygon,
            points_layer={"choices": self._get_valid_points_layers},
            image_layer={"choices": self._get_valid_image_layers},
            call_button="Lasso",
        )
        self.selection_box.addWidget(self._layer_selection_widget.native)

        self.mask_seg_box = QHBoxLayout()
        self._layer_selection_widget_mask = magicgui(
            self._mask_volume,
            image_layer={"choices": self._get_valid_image_layers},
            mask_layer={"choices": self._get_valid_mask_layers},
            masking={"choices": ["isolate", "subtract"]},
            call_button="Mask Volume",
        )
        self.mask_seg_box.addWidget(self._layer_selection_widget_mask.native)

        self.connected_components_box = QHBoxLayout()
        self._layer_selection_widget_connected_components = magicgui(
            self._connected_components,
            mask_layer={"choices": self._get_valid_image_layers},
            remove_small_objects_size={"value": 100},
            call_button="Connected Components",
        )
        self.connected_components_box.addWidget(
            self._layer_selection_widget_connected_components.native
        )

        self.display_connected_components_box = QHBoxLayout()
        self._layer_selection_widget_display_connected_components = magicgui(
            self._display_connected_components,
            components_layer={"choices": self._get_valid_image_layers},
            component_number={"value": 1},
            call_button="Display Connected Components",
        )
        self.display_connected_components_box.addWidget(
            self._layer_selection_widget_display_connected_components.native
        )

        self.store_tomogram_box = QHBoxLayout()
        self.store_tomogram_widget = magicgui(
            self._store_tomogram,
            image_layer={"choices": self._get_valid_image_layers},
            store_component_number={"value": 1, "label": "Component Number"},
            filename={
                "widget_type": "FileEdit",
                "mode": "d",
                "label": "Folder Path",
            },
            call_button="Store Tomogram",
        )
        self.store_tomogram_box.addWidget(self.store_tomogram_widget.native)

        self.setLayout(QVBoxLayout())
        self.layout().addLayout(self.annotation_box)
        self.layout().addLayout(self.selection_box)
        self.layout().addLayout(self.mask_seg_box)
        self.layout().addLayout(self.connected_components_box)
        self.layout().addLayout(self.display_connected_components_box)
        self.layout().addLayout(self.store_tomogram_box)
        # self.layout().addWidget(self._layer_selection_widget.native)

        viewer.layers.events.inserted.connect(self._on_layer_change)
        viewer.layers.events.removed.connect(self._on_layer_change)

    def _on_layer_change(self, event):
        self._layer_selection_widget.points_layer.choices = (
            self._get_valid_points_layers(None)
        )
        self._layer_selection_widget.image_layer.choices = (
            self._get_valid_image_layers(None)
        )
        self._layer_selection_widget_mask.image_layer.choices = (
            self._get_valid_image_layers(None)
        )
        self._layer_selection_widget_mask.mask_layer.choices = (
            self._get_valid_mask_layers(None)
        )
        self._layer_selection_widget_connected_components.mask_layer.choices = self._get_valid_image_layers(
            None
        )
        self._layer_selection_widget_display_connected_components.components_layer.choices = self._get_valid_image_layers(
            None
        )
        self.store_tomogram_widget.image_layer.choices = (
            self._get_valid_image_layers(None)
        )

    def _on_click_freehand(self):
        """
        This is for freehand drawing of the polygon.

        This is a preliminary implementation and is not perfect, particularly the visual feedback.
        """

        # make sure that we are in 3D view
        if self.viewer.dims.ndisplay != 3:
            napari.utils.notifications.show_warning("Please switch to 3D view")
            return

        # Initialize a dummy shape layer to get the dimensions right (3D)
        shape_layer = self.viewer.add_shapes(
            np.ones((2, 3)),
            shape_type="polygon",
            edge_color="coral",
            face_color="royalblue",
            opacity=0.5,
            name="lasso-shapes",
        )

        # Add a callback to the shape layer, imitating the 2D lasso tool
        @shape_layer.mouse_drag_callbacks.append
        def add_polygon(shape_layer, event):
            # Disable camera interaction
            self.viewer.camera.interactive = False

            # Overwrite the get_value and edit methods of the shape layer (causing problems)
            shape_layer, original_get_value, original_edit = (
                redefine_shapelayer_functions(shape_layer)
            )

            # Set the mode to ADD_POLYGON_LASSO
            shape_layer._mode = Mode.ADD_POLYGON_LASSO

            # Activate drawing mode
            generator = add_path_polygon_lasso(shape_layer, event)
            yield
            while True:
                try:
                    if event.type == "mouse_move":
                        next(generator)
                        yield
                    elif event.type == "mouse_release":
                        next(generator)
                        yield
                        generator.close()
                        break
                except StopIteration:
                    # Get points in the correct order
                    points = np.concatenate(
                        (
                            shape_layer.data[1][:2],
                            shape_layer.data[0][2:],
                            shape_layer.data[0][1:2],
                        ),
                        axis=0,
                    )

                    # Add the points to the viewer
                    self.viewer.add_points(
                        points,
                        name="lasso-points",
                        edge_color="blue",
                        face_color="blue",
                        size=2,
                    )

                    # Remove the shape layer
                    self.viewer.layers.remove("lasso-shapes")

                    # Enable camera interaction
                    self.viewer.camera.interactive = True
                    break

    def _on_click_polygon(self):
        """
        This is for manually clicking each point of the polygon.
        """
        # make sure that we are in 3D view
        if self.viewer.dims.ndisplay != 3:
            self.viewer.dims.ndisplay = 3
        # initialize a points layer
        self.viewer.add_points(
            ndim=3,
            name="lasso-points",
            edge_color="blue",
            face_color="blue",
            size=3,
        )

    def _lasso_from_polygon(
        self,
        points_layer: napari.layers.Points,
        image_layer: napari.layers.Image,
    ):
        if (points_layer is None) or (image_layer is None):
            return

        # Get the selected points
        points = points_layer.data

        # get the volume shape
        volume_shape = image_layer.data.shape

        # generate the mask
        mask = mask_via_extension(points, volume_shape)

        # add the mask to the viewer
        self.viewer.add_image(mask, name="mask")

        return

    def _mask_volume(
        self,
        image_layer: napari.layers.Image,
        mask_layer: napari.layers.Image,
        masking: str,
    ):
        if (image_layer is None) or (mask_layer is None):
            return

        # get the mask
        mask = mask_layer.data

        # get the volume
        volume = image_layer.data

        masked_volume = volume.copy()
        if masking == "isolate":
            masked_volume[~mask] = 0
        elif masking == "subtract":
            masked_volume[mask] = 0

        # add the masked volume to the viewer
        self.viewer.add_image(masked_volume, name="masked_volume")

    def _connected_components(
        self,
        mask_layer: napari.layers.Image,
        remove_small_objects_size: int,
    ):
        if mask_layer is None:
            return

        mask = mask_layer.data
        mask = mask > 0

        # get the connected components
        components, num_components = label(mask)

        # remove small objects
        max_val = np.max(components)
        i = 1
        while i < max_val + 1:
            if np.sum(components == i) < remove_small_objects_size:
                components[components == i] = 0
                components[components > i] -= 1
                max_val -= 1
            else:
                i += 1

        # add the modified mask to the viewer
        self.viewer.add_image(components, name="connected_components")

    def _display_connected_components(
        self,
        components_layer: napari.layers.Image,
        component_number: int,
    ):
        if components_layer is None:
            return

        components_layer.contrast_limits = (
            float(component_number) - 0.5,
            float(component_number) + 0.5,
        )

        colors = np.zeros((256, 4))
        colors[127] = [1, 0, 0, 1]
        colors[128] = [1, 0, 0, 1]
        custom_colormap = colormap.Colormap(colors)

        components_layer.colormap = custom_colormap

    def _store_tomogram(
        self,
        image_layer: napari.layers.Image,
        store_component_number: int,
        filename: str,
    ):
        if image_layer is None:
            return
        out_data = (image_layer.data == store_component_number) * 1.0
        out_data = np.transpose(out_data, (2, 1, 0))
        store_tomogram(filename, out_data)

    def _get_valid_points_layers(
        self, combo_box
    ) -> List[napari.layers.Points]:
        return [
            layer
            for layer in self.viewer.layers
            if isinstance(layer, napari.layers.Points)
        ]

    def _get_valid_image_layers(self, combo_box) -> List[napari.layers.Image]:
        return [
            layer
            for layer in self.viewer.layers
            if isinstance(layer, napari.layers.Image)
        ]

    def _get_valid_mask_layers(self, combo_box) -> List[napari.layers.Image]:
        image_layers = self._get_valid_image_layers(combo_box)
        # only return binary images
        return [layer for layer in image_layers if layer.data.dtype == bool]
