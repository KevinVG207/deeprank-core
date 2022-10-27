import numpy
from pdb2sql import pdb2sql
from deeprankcore.feature.biopython import add_features
from deeprankcore.tools.graph import build_residue_graph
from deeprankcore.tools.pdb import get_structure, get_residue_contact_pairs
from deeprankcore.domain.features import nodefeats


def test_add_features():
    pdb_path = "tests/data/pdb/1ATN/1ATN_1w.pdb"

    pdb = pdb2sql(pdb_path)
    try:
        structure = get_structure(pdb, "1ATN_1w")
    finally:
        pdb._close() # pylint: disable=protected-access

    residues = set([])
    for residue1, residue2 in get_residue_contact_pairs(
        pdb_path, structure, "A", "B", 8.5
    ):
        residues.add(residue1)
        residues.add(residue2)

    graph = build_residue_graph(residues, "1ATN-1w", 8.5)

    add_features(pdb_path, graph)

    assert numpy.any(
        node.features[nodefeats.HSE] != 0.0 for node in graph.nodes
    )

    assert numpy.any(
        node.features[nodefeats.RESDEPTH] != 0.0 for node in graph.nodes
    )
