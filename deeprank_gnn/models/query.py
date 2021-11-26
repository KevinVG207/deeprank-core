import os
from enum import Enum
import logging

import pdb2sql
import numpy
from scipy.spatial import distance_matrix

from deeprank_gnn.tools.pssm import parse_pssm
from deeprank_gnn.tools import BioWrappers, BSA
from deeprank_gnn.tools.pdb import get_residue_contact_pairs, get_residue_distance, get_surrounding_residues, get_structure
from deeprank_gnn.models.graph import Graph
from deeprank_gnn.domain.graph import EDGETYPE_INTERNAL, EDGETYPE_INTERFACE
from deeprank_gnn.domain.feature import *
from deeprank_gnn.domain.amino_acid import *


_log = logging.getLogger(__name__)


class Query:
    """ Represents one entity of interest, like a single residue variant or a protein-protein interface.

        Query objects are used to generate graphs from structures.
        objects of this class should be created before any model is loaded
    """

    def __init__(self, model_id, targets=None):
        """
            Args:
                model_id(str): the id of the model to load, usually a pdb accession code
                targets(dict, optional): target values associated with this query
        """

        self._model_id = model_id

        if targets is None:
            self._targets = {}
        else:
            self._targets = targets

    @property
    def model_id(self):
        return self._model_id

    @property
    def targets(self):
        return self._targets

    def __repr__(self):
        return "{}({})".format(type(self), self.get_query_id())


class SingleResidueVariantAtomicQuery(Query):
    "creates an atomic graph for a single residue variant in a pdb file"

    def __init__(self, pdb_path, chain_id, residue_number, insertion_code, wildtype_amino_acid, variant_amino_acid,
                 pssm_paths=None,
                 radius=10.0, nonbonded_distance_cutoff=4.5, bonded_distance_cutoff=1.6, disulfid_distance=2.2,
                 targets=None):
        """
            Args:
                pdb_path(str): the path to the pdb file
                chain_id(str): the pdb chain identifier of the variant residue
                residue_number(int): the number of the variant residue
                insertion_code(str): the insertion code of the variant residue, set to None if not applicable
                wildtype_amino_acid(deeprank amino acid object): the wildtype amino acid
                variant_amino_acid(deeprank amino acid object): the variant amino acid
                pssm_paths(dict(str,str), optional): the paths to the pssm files, per chain identifier
                radius(float): in Ångström, determines how many residues will be included in the graph
                nonbonded_distance_cutoff(float): max distance in Ångström between a pair of nonbonded atoms to consider them as an edge in the graph
                bonded_distance_cutoff(float): max distance in Ångström between a pair of covalently bonded atoms to consider them as an edge in the graph
                disulfid_distance(float): max distance in Ångström between two gamma sulfur atoms to consider them as a disulfid bond
                targets(dict(str,float)): named target values associated with this query
        """

        self._pdb_path = pdb_path
        self._pssm_paths = pssm_paths

        model_id = os.path.splitext(os.path.basename(pdb_path))[0]

        Query.__init__(self, model_id, targets)

        self._chain_id = chain_id
        self._residue_number = residue_number
        self._insertion_code = insertion_code
        self._wildtype_amino_acid = wildtype_amino_acid
        self._variant_amino_acid = variant_amino_acid

        self._radius = radius
        self._nonbonded_distance_cutoff = nonbonded_distance_cutoff
        self._bonded_distance_cutoff = bonded_distance_cutoff
        self._disulfid_distance = disulfid_distance

    @property
    def residue_id(self):
        "string representation of the residue number and insertion code"

        if self._insertion_code is not None:
            return "{}{}".format(self._residue_number, self._insertion_code)
        else:
            return str(self._residue_number)

    def get_query_id(self):
        return "{}:{}:{}:{}->{}".format(self.model_id, self._chain_id, self.residue_id, self._wildtype_amino_acid.name, self._variant_amino_acid.name)

    def __eq__(self, other):
        return type(self) == type(other) and self.model_id == other.model_id and \
            self._chain_id == other._chain_id and self.residue_id == other.residue_id and \
            self._wildtype_amino_acid == other._wildtype_amino_acid and self._variant_amino_acid == other._variant_amino_acid

    def __hash__(self):
        return hash((self.model_id, self._chain_id, self.residue_id, self._wildtype_amino_acid, self._variant_amino_acid))

    @staticmethod
    def _get_atom_node_key(atom):
        """ Pickle has problems serializing the graph when the nodes are atoms,
            so use this function to generate an unique key for the atom"""

        # This should include the model, chain, residue and atom
        return str(atom)

    def build_graph(self):

        # load pdb strucure
        try:
            pdb = pdb2sql.pdb2sql(self._pdb_path)

            structure = get_structure(pdb, self.model_id)
        finally:
            pdb._close()

        # read the pssm
        if self._pssm_paths is not None:
            for chain in structure.chains:
                pssm_path = self._pssm_paths[chain.id]

                with open(pssm_path, 'rt') as f:
                    chain.pssm = parse_pssm(f, chain)

        # find the variant residue
        variant_residues = [r for r in structure.get_chain(self._chain_id).residues
                            if r.number == self._residue_number and r.insertion_code == self._insertion_code]
        if len(variant_residues) == 0:
            raise ValueError("Residue {}:{} not found in {}".format(self._chain_id, self.residue_id, self._pdb_path))
        variant_residue = variant_residues[0]

        # get the residues and atoms involved
        residues = get_surrounding_residues(structure, variant_residue, self._radius)
        atoms = []
        for residue in residues:
            atoms.extend(residue.atoms)

        # build a graph and keep track of how we named the nodes
        atom_node_names = {}
        graph = Graph(self.get_query_id(), self.targets)

        # find neighbouring atoms
        atom_positions = [atom.position for atom in atoms]
        distances = distance_matrix(atom_positions, atom_positions, p=2)
        nonbonded_neighbours = distances < self._nonbonded_distance_cutoff
        for atom1_index, atom2_index in numpy.transpose(numpy.nonzero(nonbonded_neighbours)):
            if atom1_index != atom2_index:  # do not pair an atom with itself

                distance = distances[atom1_index, atom2_index]

                atom1 = atoms[atom1_index]
                atom2 = atoms[atom2_index]

                atom1_key = SingleResidueVariantAtomicQuery._get_atom_node_key(atom1)
                atom2_key = SingleResidueVariantAtomicQuery._get_atom_node_key(atom2)

                if distance < self._bonded_distance_cutoff:

                    edge_type = EDGETYPE_INTERNAL

                elif atom1.name == "SG" and atom2.name == "SG" and distance < self._disulfid_distance:

                    edge_type = EDGETYPE_INTERNAL
                else:
                    edge_type = EDGETYPE_INTERFACE

                graph.add_edge(atom1_key, atom2_key)
                graph.edges[atom1_key, atom2_key][FEATURENAME_EDGETYPE] = edge_type
                graph.edges[atom1_key, atom2_key][FEATURENAME_EDGEDISTANCE] = distance

                atom_node_names[atom1] = atom1_key
                atom_node_names[atom2] = atom2_key

        for atom, node_name in atom_node_names.items():
            node = graph.nodes[node_name]
            node[FEATURENAME_POSITION] = atom.position

        # TODO: add pssm score change of the variant
        # TODO: vanderwaals and coulomb features
        # TODO: solvent accessibility

        return graph


class ProteinProteinInterfaceResidueQuery(Query):
    "a query that builds residue-based graphs, using the residues at a protein-protein interface"

    def __init__(self, pdb_path, chain_id1, chain_id2, pssm_paths=None,
                 interface_distance_cutoff=8.5, internal_distance_cutoff=3.0,
                 use_biopython=False, targets=None):
        """
            Args:
                pdb_path(str): the path to the pdb file
                chain_id1(str): the pdb chain identifier of the first protein of interest
                chain_id2(str): the pdb chain identifier of the second protein of interest
                pssm_paths(dict(str,str), optional): the paths to the pssm files, per chain identifier
                interface_distance_cutoff(float): max distance in Ångström between two interacting residues of the two proteins
                internal_distance_cutoff(float): max distance in Ångström between two interacting residues within the same protein
                use_biopython(bool): whether or not to use biopython tools
                targets(dict, optional): named target values associated with this query
        """

        model_id = os.path.splitext(os.path.basename(pdb_path))[0]

        Query.__init__(self, model_id, targets)

        self._pdb_path = pdb_path

        self._chain_id1 = chain_id1
        self._chain_id2 = chain_id2

        self._pssm_paths = pssm_paths

        self._interface_distance_cutoff = interface_distance_cutoff
        self._internal_distance_cutoff = internal_distance_cutoff

        self._use_biopython = use_biopython

    def get_query_id(self):
        return "{}:{}-{}".format(self.model_id, self._chain_id1, self._chain_id2)

    def __eq__(self, other):
        return type(self) == type(other) and self.model_id == other.model_id and \
            {self._chain_id1, self._chain_id2} == {other._chain_id1, other._chain_id2}

    def __hash__(self):
        return hash((self.model_id, tuple(sorted([self._chain_id1, self._chain_id2]))))

    @staticmethod
    def _residue_is_valid(residue):
        if residue.amino_acid is None:
            return False

        if residue not in residue.chain.pssm:
            _log.debug("{} not in pssm".format(residue))
            return False

        return True

    @staticmethod
    def _get_residue_node_key(residue):
        """ Pickle has trouble serializing a graph if the keys are residue objects, so
            we map the residues to string identifiers
        """

        # this should include everything to identify the residue: structure, chain, number, insertion_code
        return str(residue)

    def build_graph(self):
        """ Builds the residue graph.

            Returns(deeprank graph object): the resulting graph
        """

        # get residues from the pdb

        interface_pairs = get_residue_contact_pairs(self._pdb_path, self.model_id,
                                                    self._chain_id1, self._chain_id2,
                                                    self._interface_distance_cutoff)
        if len(interface_pairs) == 0:
            raise ValueError("no interface residues found")

        interface_pairs_list = list(interface_pairs)

        model = interface_pairs_list[0].item1.chain.model
        chain1 = model.get_chain(self._chain_id1)
        chain2 = model.get_chain(self._chain_id2)

        # read the pssm
        if self._pssm_paths is not None:
            for chain in (chain1, chain2):
                pssm_path = self._pssm_paths[chain.id]

                with open(pssm_path, 'rt') as f:
                    chain.pssm = parse_pssm(f, chain)

        # separate residues by chain
        residues_from_chain1 = set([])
        residues_from_chain2 = set([])
        for residue1, residue2 in interface_pairs:

            if self._residue_is_valid(residue1):
                if residue1.chain.id == self._chain_id1:
                    residues_from_chain1.add(residue1)

                elif residue1.chain.id == self._chain_id2:
                    residues_from_chain2.add(residue1)

            if self._residue_is_valid(residue2):
                if residue2.chain.id == self._chain_id1:
                    residues_from_chain1.add(residue2)

                elif residue2.chain.id == self._chain_id2:
                    residues_from_chain2.add(residue2)

        # create the graph
        graph = Graph(self.get_query_id(), self.targets)

        # These will not be stored in the graph, but we need them to get features.
        residues_by_node = {}

        # interface edges
        for pair in interface_pairs:

            residue1, residue2 = pair
            if self._residue_is_valid(residue1) and self._residue_is_valid(residue2):

                distance = get_residue_distance(residue1, residue2)

                key1 = ProteinProteinInterfaceResidueQuery._get_residue_node_key(residue1)
                key2 = ProteinProteinInterfaceResidueQuery._get_residue_node_key(residue2)

                residues_by_node[key1] = residue1
                residues_by_node[key2] = residue2

                graph.add_edge(key1, key2)
                graph.edges[key1, key2][FEATURENAME_EDGEDISTANCE] = distance
                graph.edges[key1, key2][FEATURENAME_EDGETYPE] = EDGETYPE_INTERFACE

        # internal edges
        for residue_set in (residues_from_chain1, residues_from_chain2):
            residue_list = list(residue_set)
            for index, residue1 in enumerate(residue_list):
                for residue2 in residue_list[index + 1:]:
                    distance = get_residue_distance(residue1, residue2)

                    if distance < self._internal_distance_cutoff:
                        key1 = ProteinProteinInterfaceResidueQuery._get_residue_node_key(residue1)
                        key2 = ProteinProteinInterfaceResidueQuery._get_residue_node_key(residue2)

                        residues_by_node[key1] = residue1
                        residues_by_node[key2] = residue2

                        graph.add_edge(key1, key2)
                        graph.edges[key1, key2][FEATURENAME_EDGEDISTANCE] = distance
                        graph.edges[key1, key2][FEATURENAME_EDGETYPE] = EDGETYPE_INTERNAL

        # get bsa
        pdb = pdb2sql.interface(self._pdb_path)
        try:
            bsa_calc = BSA.BSA(self._pdb_path, pdb)
            bsa_calc.get_structure()
            bsa_calc.get_contact_residue_sasa(cutoff=self._interface_distance_cutoff)
            bsa_data = bsa_calc.bsa_data
        finally:
            pdb._close()

        # get biopython features
        if self._use_biopython:
            bio_model = BioWrappers.get_bio_model(self._pdb_path)
            residue_depths = BioWrappers.get_depth_contact_res(bio_model,
                                                               [(residue.chain.id, residue.number, residue.amino_acid.three_letter_code)
                                                                for residue in residues_by_node.values()])
            hse = BioWrappers.get_hse(bio_model)

        # add node features
        chain_codes = {chain1: 0.0, chain2: 1.0}
        for node_key, node in graph.nodes.items():
            residue = residues_by_node[node_key]

            bsa_key = (residue.chain.id, residue.number, residue.amino_acid.three_letter_code)
            bio_key = (residue.chain.id, residue.number)

            pssm_row = residue.get_pssm()
            pssm_value = [pssm_row.conservations[amino_acid] for amino_acid in self.amino_acid_order]

            node[FEATURENAME_CHAIN] = chain_codes[residue.chain]
            node[FEATURENAME_POSITION] = numpy.mean([atom.position for atom in residue.atoms], axis=0)
            node[FEATURENAME_AMINOACID] = residue.amino_acid.onehot
            node[FEATURENAME_CHARGE] = residue.amino_acid.charge
            node[FEATURENAME_POLARITY] = residue.amino_acid.polarity.onehot
            node[FEATURENAME_BURIEDSURFACEAREA] = bsa_data[bsa_key]

            if self._pssm_paths is not None:
                node[FEATURENAME_PSSM] = pssm_value
                node[FEATURENAME_CONSERVATION] = pssm_row.conservations[residue.amino_acid]
                node[FEATURENAME_INFORMATIONCONTENT] = pssm_row.information_content

            if self._use_biopython:
                node[FEATURENAME_RESIDUEDEPTH] = residue_depths[residue] if residue in residue_depths else 0.0
                node[FEATURENAME_HALFSPHEREEXPOSURE] = hse[bio_key] if bio_key in hse else (0.0, 0.0, 0.0)

        return graph

    amino_acid_order = [alanine, arginine, asparagine, aspartate, cysteine, glutamine, glutamate, glycine, histidine, isoleucine,
                        leucine, lysine, methionine, phenylalanine, proline, serine, threonine, tryptophan, tyrosine, valine]


class QueryDataset:
    "represents a collection of data queries"

    def __init__(self):
        self._queries = []

    def add(self, query):
        self._queries.append(query)

    @property
    def queries(self):
        return self._queries

    def __contains__(self, query):
        return query in self._queries

    def __iter__(self):
        return iter(self._queries)
