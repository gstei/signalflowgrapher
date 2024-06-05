from PyQt5 import QtCore, QtGui
from PyQt5.Qt import Qt, QPoint, QMouseEvent, QRubberBand, QRect, QSize, \
    QResizeEvent
from PyQt5.QtWidgets import QWidget
from signalflowgrapher.gui.grid import FixedGrid, NoneGrid
from signalflowgrapher.gui.fixed_grid_widget import FixedGridWidget
from signalflowgrapher.gui.branch_widget import \
    BranchWidget, Spline1HandleWidget, Spline2HandleWidget, \
    SplineHandleWidgetMoveEvent, SplineHandleWidgetPressEvent, \
    SplineHandleWidgetReleaseEvent, WidgetClickEvent
from signalflowgrapher.commands.command_handler import CommandHandler
from signalflowgrapher.model.model import \
    Model, CurvedBranchAddedEvent, CurvedBranchRemovedEvent, \
    CurvedBranchTransformedEvent, GraphChangedEvent, GraphMovedEvent, \
    LabelChangedTextEvent, LabelMovedEvent, \
    LabeledObject, PositionedNodeAddedEvent, \
    PositionedNodeMovedEvent, PositionedNodeRemovedEvent
from signalflowgrapher.gui.node_widget import NodeWidget
from signalflowgrapher.controllers.main_controller import MainController
from signalflowgrapher.gui.label_widget import LabelWidget
from signalflowgrapher.gui.graph_item import \
    WidgetMoveEvent, WidgetPressEvent, WidgetReleaseEvent, GraphItem
from signalflowgrapher.common.observable import ValueObservable
import logging
logger = logging.getLogger(__name__)


class GraphField(QWidget):
    def __init__(self,
                 controller: MainController,
                 model: Model,
                 command_handler: CommandHandler):
        super(GraphField, self).__init__()
        self.__controller = controller
        self.__model = model
        self.__command_handler = command_handler

        self.__model.observe(self.__handle_model_change)
        self.__selection = list()
        self.selection = ValueObservable(())
        self.__handles = list()
        self.__model_widget_map = {}
        self.__widget_model_map = {}
        self.__model_label_map = {}
        self.__label_model_map = {}
        self.__mouse_press_pos: QPoint = None
        self.__selection_rect = None
        self.__grid_size = 30
        self.__grid = FixedGrid(self.__grid_size)
        self.__grid_widget = FixedGridWidget(self.__grid_size, parent=self)
        self.__grid_widget.resize(self.size())
        self.__grid_widget.show()
        self.__grid_offset = QPoint()
        self.__rubber_band: QRubberBand = QRubberBand(
            QRubberBand.Rectangle, self)

        self.setMinimumSize(800, 600)

    def on_esc_press(self):
        self.__clear_selection()

    def on_ctrl_press(self):
        self.__grid = NoneGrid()
        # self.__grid_widget.hide()

    def on_ctrl_release(self):
        self.__grid = FixedGrid(self.__grid_size)
        self.__grid.set_offset(self.__grid_offset)
        self.__grid_widget.lower()
        # self.__grid_widget.show()

    def __selection_changed(self):
        self.selection.set(tuple(self.__widget_model_map.get(widget)
                                 for widget in self.__selection))

    def mousePressEvent(self, event: QMouseEvent):
        logger.debug("MousePressEvent")
        if event.buttons() == Qt.LeftButton:
            self.__mouse_press_pos = event.globalPos()
            self.__command_handler.start_script()

            if event.modifiers() == Qt.AltModifier:
                self.__rubber_band.setGeometry(
                    QRect(self.__mouse_press_pos, QSize()))
                self.__rubber_band.show()
                self.__clear_selection()

    def mouseReleaseEvent(self, event: QMouseEvent):
        logger.debug("MouseReleaseEvent")
        if self.__mouse_press_pos is not None:
            self.__command_handler.end_script()
        self.__mouse_press_pos = None
        self.setCursor(QtGui.QCursor(QtCore.Qt.ArrowCursor))

        if self.__rubber_band.isVisible():
            self.__rubber_band.hide()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.LeftButton:
            grid_pos = self.__grid.get_grid_position(event.pos())
            self.__controller.create_node(grid_pos.x(), grid_pos.y())

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.__mouse_press_pos is not None:
            global_position = event.globalPos()
            diff = global_position - self.__mouse_press_pos
            if self.__rubber_band.isVisible():
                self.__rubber_band.setGeometry(
                    QRect(self.mapFromGlobal(self.__mouse_press_pos),
                          event.pos()).normalized())
                # Add to selection if inside rubber band remove otherwise
                for widget in self.__model_widget_map.values():
                    if self.__rubber_band.geometry().contains(
                            widget.geometry()):
                        self.__add_selection(widget)
                    else:
                        self.__remove_selection(widget)
            else:
                self.setCursor(QtGui.QCursor(QtCore.Qt.ClosedHandCursor))
                self.__grid_offset += diff
                self.__grid.set_offset(self.__grid_offset)
                self.__grid_widget.set_offset(self.__grid_offset)
                self.__grid_widget.repaint()
                self.__model.move_graph_relative(diff.x(), diff.y())
                self.__mouse_press_pos = global_position

    def __on_label_click(self, event):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.start_script()
                self.__grid.start_move()
                return

        if isinstance(event, WidgetReleaseEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.end_script()
                model = self.__label_model_map[event.widget]
                widget = self.__model_widget_map[model]
                self.__handle_widget_release(widget, event.mouse_event)
                return

        if isinstance(event, WidgetMoveEvent):
            label_model = self.__label_model_map[event.widget]
            grid_move = self.__grid.relative_move(event.dx,
                                                  event.dy,
                                                  event.widget)
            self.__controller.move_label_relative(label_model,
                                                  grid_move.x(),
                                                  grid_move.y())
            widget = self.__model_widget_map[label_model]
            if event.widget not in self.__selection:
                self.__clear_selection()
                self.__add_selection(widget)

    def __on_node_click(self, event):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.start_script()
                self.__grid.start_move()
                return

        if isinstance(event, WidgetReleaseEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__command_handler.end_script()

                # Do not modify selection after move
                if not event.press_pos == event.mouse_event.globalPos():
                    return

                if event.mouse_event.modifiers() == Qt.ControlModifier:
                    if len(self.__selection) == 1 and \
                            isinstance(self.__selection[0], NodeWidget):
                        start = self.__widget_model_map[self.__selection[0]]
                        end = self.__widget_model_map[event.widget]
                        if start == end:
                            self.__controller.create_self_loop(start)
                        else:
                            self.__controller.create_branch_auto_pos(
                                start, end)

                        self.__clear_selection()
                        self.__add_selection(event.widget)
                        return

                return self.__handle_widget_release(event.widget,
                                                    event.mouse_event)

        if isinstance(event, WidgetMoveEvent):
            if event.widget not in self.__selection:
                self.__clear_selection()
                self.__add_selection(event.widget)

            grid_move = self.__grid.relative_move(
                event.dx,
                event.dy,
                event.widget)

            for widget in self.__selection:
                if isinstance(widget, NodeWidget):
                    node = self.__widget_model_map[widget]
                    if grid_move.x() != 0 or grid_move.y() != 0:
                        self.__controller.move_node(node,
                                                    grid_move.x(),
                                                    grid_move.y())

    def __on_branch_click(self, event: WidgetPressEvent):
        if isinstance(event, WidgetPressEvent):
            if event.mouse_event.button() == Qt.LeftButton:
                self.__handle_widget_release(event.widget, event.mouse_event)
                if len(self.__selection) == 1 \
                   and event.widget in self.__selection:
                    self.__handles = event.widget.get_handles()
                    for handle in self.__handles:
                        handle.observe(
                            self.__on_spline_handle_click)
                        handle.show()

    def __handle_widget_release(self,
                                widget: GraphItem,
                                mouse_event: QMouseEvent):
        if not mouse_event.modifiers() == Qt.ShiftModifier:
            self.__clear_selection()

        # Clear visible handles
        self.__clear_handles()

        if widget in self.__selection:
            self.__remove_selection(widget)
        else:
            self.__add_selection(widget)

    def __on_spline_handle_click(self, event: WidgetClickEvent):
        if isinstance(event, SplineHandleWidgetPressEvent) \
           and event.mouse_event.button() == Qt.LeftButton:
            self.__command_handler.start_script()
            self.__grid.start_move()

        if isinstance(event, SplineHandleWidgetReleaseEvent) \
           and event.mouse_event.button() == Qt.LeftButton:
            self.__command_handler.end_script()

        if isinstance(event, SplineHandleWidgetMoveEvent):
            widget = event.widget
            dx1, dy1, dx2, dy2 = 0, 0, 0, 0
            grid_move = self.__grid.relative_move(event.dx,
                                                  event.dy,
                                                  event.widget)
            if isinstance(widget, Spline1HandleWidget):
                dx1, dy1 = grid_move.x(), grid_move.y()
            elif isinstance(widget, Spline2HandleWidget):
                dx2, dy2 = grid_move.x(), grid_move.y()
            self.__controller.transform_branch(
                widget.get_branch(), -dx1, -dy1, -dx2, -dy2)

    def get_selection(self):
        return self.__selection.copy()

    def select_all(self):
        self.__clear_selection()
        for widget in self.__model_widget_map.values():
            self.__add_selection(widget)

    def __clear_handles(self):
        # Remove all handles for next selection
        for handle in self.__handles:
            handle.deleteLater()
        self.__handles.clear()

    def __clear_selection(self):
        self.__clear_handles()

        for widget in self.__selection:
            widget.unselect()

        for label in self.__model_label_map.values():
            label.unselect()

        self.__selection.clear()
        self.update()
        self.__selection_changed()

    def __add_selection(self, widget):
        if (widget not in self.__selection):
            self.__selection.append(widget)
            widget.select(len(self.__selection))

            # Select label
            model = self.__widget_model_map[widget]
            label = self.__model_label_map[model]
            label.select(len(self.__selection))

            self.update()
            self.__selection_changed()

    def __remove_selection(self, widget):
        if widget in self.__selection:
            remove_selection_number = widget.get_selection_number()
            self.__selection.remove(widget)
            widget.unselect()

            # Deselect label
            model = self.__widget_model_map[widget]
            label = self.__model_label_map[model]
            label.unselect()

            # Adjust selection index for other widgets
            for sel in self.__selection:
                if sel.get_selection_number() > remove_selection_number:
                    sel.select(sel.get_selection_number() - 1)

            self.update()
            self.__selection_changed()

    def __handle_model_change(self, event):
        if isinstance(event, PositionedNodeAddedEvent):
            logger.debug("PositionedNodeAddedEvent received")
            self.__add_node(event.node)
            return
        if isinstance(event, PositionedNodeRemovedEvent):
            logger.debug("PositionedNodeRemovedEvent received")
            widget = self.__model_widget_map[event.node]
            widget.deleteLater()
            self.__clear_selection()

            self.__model_widget_map.pop(event.node)
            self.__widget_model_map.pop(widget)

            self.__remove_label_relative(event.node)
            return
        if isinstance(event, CurvedBranchAddedEvent):
            logger.debug("CurvedBranchAddedEvent received")
            self.__add_branch(event.branch)
            return
        if isinstance(event, CurvedBranchRemovedEvent):
            logger.debug("CurvedBranchRemovedEvent received")
            widget = self.__model_widget_map[event.branch]
            self.__clear_selection()
            widget.deleteLater()

            self.__model_widget_map.pop(event.branch)
            self.__widget_model_map.pop(widget)

            self.__remove_label_relative(event.branch)
            return
        if isinstance(event, PositionedNodeMovedEvent):
            # Propagate event to nodes, branches
            for widget in self.__model_widget_map.values():
                if isinstance(widget, NodeWidget):
                    widget.node_moved_event(event)
                elif isinstance(widget, BranchWidget):
                    widget.node_moved_event(event)

            # Propagate event to active handles
            for handle in self.__handles:
                handle.node_moved_event(event)

            # Propagate event to labels
            for label in self.__model_label_map.values():
                label.node_moved_event(event)
            return
        if isinstance(event, CurvedBranchTransformedEvent):
            # Propagate event to handles
            for handle in self.__handles:
                handle.branch_transformed_event(event)

            # Propagate event to branches
            for widget in self.__model_widget_map.values():
                if isinstance(widget, BranchWidget):
                    widget.branch_transformed_event(event)

            # Propagate event to labels
            for label in self.__model_label_map.values():
                label.branch_transformed_event(event)
            return
        if isinstance(event, LabelChangedTextEvent):
            logger.debug("LabelChangedTextEvent received")
            label = self.__model_label_map[event.labeled_obj]
            label.setText(event.new_text)
            label.adjustSize()

            # Propagate event to label
            label.label_changed_text_event(event)
            return
        if isinstance(event, LabelMovedEvent):
            label = self.__model_label_map[event.labeled_obj]
            label.label_moved_event(event)
        if isinstance(event, GraphChangedEvent):
            logger.debug("GraphChangedEvent received")
            self.__clear_selection()
            for widget in self.__widget_model_map:
                widget.deleteLater()
            for label in self.__label_model_map:
                label.deleteLater()

            self.__model_widget_map.clear()
            self.__widget_model_map.clear()
            self.__label_model_map.clear()
            self.__model_label_map.clear()
            for node in event.nodes:
                self.__add_node(node)
            for branch in event.branches:
                self.__add_branch(branch)
            return
        if isinstance(event, GraphMovedEvent):
            for widget in self.__model_widget_map.values():
                widget.graph_moved_event(event)

            for widget in self.__model_label_map.values():
                widget.graph_moved_event(event)

            for widget in self.__handles:
                widget.graph_moved_event(event)

    def __add_node(self, node):
        widget = NodeWidget(node, parent=self)
        # Set initial position centered to given point
        widget.move(QPoint(int(node.x - widget.width() / 2),
                           int(node.y - widget.height() / 2)))
        widget.observe(self.__on_node_click)
        self.__model_widget_map[node] = widget
        self.__widget_model_map[widget] = node
        widget.show()
        self.__initalize_label(node)
        self.__clear_selection()
        self.__add_selection(widget)

    def __add_branch(self, branch):
        widget = BranchWidget(branch,
                              QPoint(int(branch.spline1_x),
                                     int(branch.spline1_y)),
                              QPoint(int(branch.spline2_x),
                                     int(branch.spline2_y)),
                              parent=self)

        self.__model_widget_map[branch] = widget
        self.__widget_model_map[widget] = branch
        widget.show()

        # Lower branch to ensure it is behind its nodes
        widget.lower()

        # Lower grid widget to keep it behind the branches
        self.__grid_widget.lower()

        # Register click listener for widget
        widget.observe(self.__on_branch_click)

        # Paint widget explicit
        # because the label positioning needs an existing
        # Bézier curve
        widget.repaint()
        self.__initalize_label(branch)
        self.__clear_selection()
        self.__add_selection(widget)

    def __initalize_label(self, labeled_object: LabeledObject):
        widget = self.__model_widget_map[labeled_object]
        label = LabelWidget(labeled_object.label_text,
                            labeled_object,
                            widget,
                            parent=self)

        self.__model_label_map[labeled_object] = label
        self.__label_model_map[label] = labeled_object

        label.observe(self.__on_label_click)
        label.show()

    def __remove_label_relative(self, labeled_object: LabeledObject):
        label = self.__model_label_map[labeled_object]
        label.deleteLater()
        self.__model_label_map.pop(labeled_object)
        self.__label_model_map.pop(label)

    def resizeEvent(self, event: QResizeEvent):
        # Resize grid
        self.__grid_widget.resize(self.size())
        super().resizeEvent(event)
