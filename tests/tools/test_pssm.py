from pdb2sql import pdb2sql
from deeprank_gnn.tools.pssm import parse_pssm
from deeprank_gnn.tools.pdb import get_structure
from deeprank_gnn.domain.amino_acid import alanine


def test_add_pssm():
    pdb = pdb2sql("tests/data/pdb/1ATN/1ATN_1w.pdb")
    try:
        structure = get_structure(pdb, "1ATN")
    finally:
        pdb._close()

    for chain in structure.chains:
        with open("tests/data/pssm/1ATN/1ATN.{}.pdb.pssm".format(chain.id), 'rt') as f:
            chain.pssm = parse_pssm(f, chain)

    # Verify that each residue is present and that the data makes sense:
    for chain in structure.chains:
        for residue in chain.residues:
            assert residue in chain.pssm
            assert type(chain.pssm[residue].information_content) == float
            assert type(chain.pssm[residue].conservations[alanine]) == float
