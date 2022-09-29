import unittest
from deeprankcore.DataSet import HDF5DataSet, save_hdf5_keys, _DivideDataSet
from torch_geometric.data.data import Data
import h5py
from deeprankcore.domain.feature import(
    FEATURE_NODE_POLARITY,
    FEATURE_NODE_RESTYPE,
    FEATURE_NODE_BURIEDSURFACEAREA,
    FEATURE_NODE_HALFSPHEREEXPOSURE,
    FEATURE_NODE_INFORMATIONCONTENT,
    FEATURE_NODE_PSSM
)

class TestDataSet(unittest.TestCase):
    def setUp(self):
        self.hdf5_path = "tests/hdf5/1ATN_ppi.hdf5"

    def test_dataset(self):
        HDF5DataSet(
            hdf5_path=self.hdf5_path,
            node_feature=["res_type", "polarity", "bsa", "depth", "hse", "ic", "pssm"],
            edge_feature=["dist"],
            target="irmsd",
            subset=None,
        )

    def test_dataset_filter(self):
        HDF5DataSet(
            hdf5_path=self.hdf5_path,
            node_feature=["res_type", "polarity", "bsa", "depth", "hse", "ic", "pssm"],
            edge_feature=["dist"],
            target="irmsd",
            subset=None,
            dict_filter={"irmsd": "<10"},
        )

    def test_transform(self):

        def operator(data: Data):
            data.x = data.x / 10
            return data

        dataset = HDF5DataSet(
            hdf5_path=self.hdf5_path,
            node_feature=["type", "polarity", "bsa", "depth", "hse", "ic", "pssm"],
            edge_feature=["dist"],
            target="irmsd",
            subset=None,
            transform=operator
        )

        assert dataset.len() > 0
        assert dataset.get(0) is not None

    def test_multi_file_dataset(self):
        dataset = HDF5DataSet(
            hdf5_path=["tests/hdf5/train.hdf5", "tests/hdf5/valid.hdf5"],
            node_feature=["type", "polarity", "bsa", "depth", "hse", "ic", "pssm"],
            edge_feature=["dist"],
            target="binary"
        )

        assert dataset.len() > 0
        assert dataset.get(0) is not None

    def test_save_external_links(self):
        n = 2

        with h5py.File("tests/hdf5/test.hdf5", 'r') as hdf5:
            original_ids = list(hdf5.keys())
        
        save_hdf5_keys("tests/hdf5/test.hdf5", original_ids[:n], "tests/hdf5/test_resized.hdf5")

        with h5py.File("tests/hdf5/test_resized.hdf5", 'r') as hdf5:
            new_ids = list(hdf5.keys())
            assert all(isinstance(hdf5.get(key, getlink=True), h5py.ExternalLink) for key in hdf5.keys())
  
        assert len(new_ids) == n
        for new_id in new_ids:
            assert new_id in original_ids

    def test_save_hard_links(self):
        n = 2

        with h5py.File("tests/hdf5/test.hdf5", 'r') as hdf5:
            original_ids = list(hdf5.keys())
        
        save_hdf5_keys("tests/hdf5/test.hdf5", original_ids[:n], "tests/hdf5/test_resized.hdf5", hardcopy = True)

        with h5py.File("tests/hdf5/test_resized.hdf5", 'r') as hdf5:
            new_ids = list(hdf5.keys())
            assert all(isinstance(hdf5.get(key, getlink=True), h5py.HardLink) for key in hdf5.keys())
  
        assert len(new_ids) == n
        for new_id in new_ids:
            assert new_id in original_ids

    def test_trainsize(self):
        hdf5 = "tests/hdf5/train.hdf5"
        hdf5_file = h5py.File(hdf5, 'r')    # contains 44 datapoints
        n_val = int ( 0.25 * len(hdf5_file) )
        n_train = len(hdf5_file) - n_val
        test_cases = [None, 0.25, n_val]
        
        for t in test_cases:
            dataset_train, dataset_val =_DivideDataSet(
                dataset = HDF5DataSet(hdf5_path=hdf5),
                val_size=t,
            )

            assert len(dataset_train) == n_train
            assert len(dataset_val) == n_val

        hdf5_file.close()
        
    def test_invalid_trainsize(self):

        hdf5 = "tests/hdf5/train.hdf5"
        hdf5_file = h5py.File(hdf5, 'r')    # contains 44 datapoints
        n = len(hdf5_file)
        test_cases = [
            1.0, n,     # cannot be 100% validation data
            -0.5, -1,   # no negative values 
            1.1, n + 1, # cannot use more than all data as input
            ]
        
        for t in test_cases:
            print(t)
            with self.assertRaises(ValueError):
                _DivideDataSet(
                    dataset = HDF5DataSet(hdf5_path=hdf5),
                    val_size=t,
                )
        
        hdf5_file.close()

    def test_subset(self):
        hdf5 = h5py.File("tests/hdf5/train.hdf5", 'r')  # contains 44 datapoints
        hdf5_keys = list(hdf5.keys())
        n = 10
        subset = hdf5_keys[:n]

        dataset = HDF5DataSet(
            hdf5_path="tests/hdf5/train.hdf5",
            subset=subset,
        )

        assert n == len(dataset)

        hdf5.close()
        

if __name__ == "__main__":
    unittest.main()
