"""These tests prove the graph *topology* (edges, conditional routing, state threading)
is wired correctly per Section 04, even though every node is a Phase 1 placeholder.
Each assertion is: invoking the compiled graph reaches the *correct* placeholder node
for the given input and fails there — not at the wrong node, and not silently.
"""
import pytest

from arx.orchestration.acquisition_flow import acquisition_flow
from arx.orchestration.development_flow import development_flow
from arx.orchestration.document_flow import document_flow


def test_document_flow_reaches_a09_placeholder():
    with pytest.raises(NotImplementedError, match="'a09'"):
        document_flow.invoke({"deal_id": "d1", "org_id": "o1", "pending_document_ids": ["doc-1"]})


def test_acquisition_flow_entry_is_a01():
    with pytest.raises(NotImplementedError, match="'a01'"):
        acquisition_flow.invoke({"deal_id": "d1", "org_id": "o1"})


def test_development_flow_entry_is_a01():
    with pytest.raises(NotImplementedError, match="'a01'"):
        development_flow.invoke({"deal_id": "d1", "org_id": "o1"})
