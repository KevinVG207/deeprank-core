from typing import Optional
import numpy
from deeprankcore.models.variant import SingleResidueVariant
from deeprankcore.models.amino_acid import amino_acids
from deeprankcore.models.structure import Residue, Atom
from deeprankcore.models.graph import Graph
from deeprankcore.domain.features import nodefeats as Nfeat

profile_amino_acid_order = sorted(amino_acids, key=lambda aa: aa.one_letter_code)


def add_features( # pylint: disable=unused-argument
    pdb_path: str, graph: Graph,
    single_amino_acid_variant: Optional[SingleResidueVariant] = None):

    for node in graph.nodes:
        if isinstance(node.id, Residue):
            residue = node.id

        elif isinstance(node.id, Atom):
            atom = node.id
            residue = atom.residue
        else:
            raise TypeError(f"Unexpected node type: {type(node.id)}")

        pssm_row = residue.get_pssm()

        profile = numpy.array([pssm_row.get_conservation(amino_acid)
                               for amino_acid in profile_amino_acid_order])

        node.features[Nfeat.PSSM] = profile
        node.features[Nfeat.INFOCONTENT] = pssm_row.information_content

        if single_amino_acid_variant is not None:

            if residue == single_amino_acid_variant.residue:
                # only the variant residue can have a variant and wildtype amino acid

                conservation_wildtype = pssm_row.get_conservation(single_amino_acid_variant.wildtype_amino_acid)
                conservation_variant = pssm_row.get_conservation(single_amino_acid_variant.variant_amino_acid)

                node.features[Nfeat.CONSERVATION] = conservation_wildtype
                node.features[Nfeat.DIFFCONSERVATION] = conservation_variant - conservation_wildtype
            else:
                # all nodes must have the same features, so set them to zero here
                node.features[Nfeat.CONSERVATION] = 0.0
                node.features[Nfeat.DIFFCONSERVATION] = 0.0