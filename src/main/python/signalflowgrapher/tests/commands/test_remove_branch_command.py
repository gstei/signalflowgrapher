import unittest
from unittest.mock import Mock, MagicMock
from signalflowgrapher.commands.remove_branch_command \
    import RemoveBranchCommand
from signalflowgrapher.model.model import CurvedBranch, \
    PositionedNode, ObservableGraph


class TestRemoveBranchCommand(unittest.TestCase):
    def test_undo(self):
        # Prepare
        model_mock = MagicMock(ObservableGraph)
        start_node = Mock(PositionedNode)
        end_node = Mock(PositionedNode)
        branch_mock = Mock(CurvedBranch)
        branch_mock.start = start_node
        branch_mock.end = end_node
        command = RemoveBranchCommand(model_mock, branch_mock)

        # Execute
        command.undo()

        # Assert
        branch_mock.reconnect \
            .assert_called_once_with(start_node, end_node)

    def test_redo(self):
        # Prepare
        model_mock = MagicMock(ObservableGraph)
        branch_mock = Mock(CurvedBranch)
        command = RemoveBranchCommand(model_mock, branch_mock)

        # Execute
        command.redo()

        # Assert
        branch_mock.remove.assert_called_once()
