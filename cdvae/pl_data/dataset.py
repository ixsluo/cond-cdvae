import pickle
from pathlib import Path

import hydra
import numpy as np
import omegaconf
import pandas as pd
import torch
from omegaconf import ValueNode
from torch.utils.data import Dataset
from torch_geometric.data import Data

from cdvae.common.data_utils import (
    add_scaled_lattice_prop,
    preprocess,
    preprocess_tensors,
)
from cdvae.common.utils import PROJECT_ROOT


class CrystDataset(Dataset):
    def __init__(
        self,
        name: ValueNode,
        path: ValueNode,  # original crystal info
        save_path: ValueNode,  # processed graph data
        force_process: ValueNode,  # process or load
        prop: ValueNode,
        niggli: ValueNode,
        primitive: ValueNode,
        graph_method: ValueNode,
        preprocess_workers: ValueNode,
        lattice_scale_method: ValueNode,
        **kwargs,
    ):
        super().__init__()
        self.path = path
        self.save_path = save_path
        self.force_process = force_process
        self.name = name
        self.prop = prop
        self.niggli = niggli
        self.primitive = primitive
        self.graph_method = graph_method
        self.lattice_scale_method = lattice_scale_method

        if self.force_process or not Path(self.save_path).exists():
            self.cached_data = preprocess(
                self.path,
                preprocess_workers,
                niggli=self.niggli,
                primitive=self.primitive,
                graph_method=self.graph_method,
                prop_list=[prop],
            )
            print(f"Dump into {self.save_path} ...")
            pickle.dump(self.cached_data, open(self.save_path, 'wb'))
        else:
            print(f"Load from {self.save_path} ...")
            self.cached_data = pickle.load(open(self.save_path, 'rb'))

        add_scaled_lattice_prop(self.cached_data, lattice_scale_method)
        self.lattice_scaler = None
        self.scaler = None

    def __len__(self) -> int:
        return len(self.cached_data)

    def __getitem__(self, index) -> Data:
        data_dict = self.cached_data[index]

        # scaler is set in DataModule set stage
        # if (self.lattice_scaler is None) or (self.scaler is None):
        #     raise ValueError("Scaler should be set before used")
        prop = self.scaler.transform(torch.tensor(data_dict[self.prop]))
        (
            frac_coords,
            atom_types,
            lengths,
            angles,
            edge_indices,
            to_jimages,
            num_atoms,
        ) = data_dict['graph_arrays']

        # atom_coords are fractional coordinates
        # edge_index is incremented during batching
        # https://pytorch-geometric.readthedocs.io/en/latest/notes/batching.html
        data = Data(
            frac_coords=torch.Tensor(frac_coords),
            atom_types=torch.LongTensor(atom_types),
            lengths=torch.Tensor(lengths).view(1, -1),
            angles=torch.Tensor(angles).view(1, -1),
            edge_index=torch.LongTensor(edge_indices.T).contiguous(),
            # shape (2, num_edges)
            to_jimages=torch.LongTensor(to_jimages),
            num_atoms=num_atoms,
            num_bonds=edge_indices.shape[0],
            num_nodes=num_atoms,  # special attribute used for batching in pytorch geometric
            y=prop.view(1, -1),
        )
        return data

    def __repr__(self) -> str:
        return f"CrystDataset({self.name=}, {self.path=}, {self.save_path=})"


class TensorCrystDataset(Dataset):
    def __init__(
        self,
        crystal_array_list,
        niggli,
        primitive,
        graph_method,
        preprocess_workers,
        lattice_scale_method,
        **kwargs,
    ):
        super().__init__()
        self.niggli = niggli
        self.primitive = primitive
        self.graph_method = graph_method
        self.lattice_scale_method = lattice_scale_method

        self.cached_data = preprocess_tensors(
            crystal_array_list,
            niggli=self.niggli,
            primitive=self.primitive,
            graph_method=self.graph_method,
        )

        add_scaled_lattice_prop(self.cached_data, lattice_scale_method)
        self.lattice_scaler = None
        self.scaler = None

    def __len__(self) -> int:
        return len(self.cached_data)

    def __getitem__(self, index):
        data_dict = self.cached_data[index]

        (
            frac_coords,
            atom_types,
            lengths,
            angles,
            edge_indices,
            to_jimages,
            num_atoms,
        ) = data_dict['graph_arrays']

        # atom_coords are fractional coordinates
        # edge_index is incremented during batching
        # https://pytorch-geometric.readthedocs.io/en/latest/notes/batching.html
        data = Data(
            frac_coords=torch.Tensor(frac_coords),
            atom_types=torch.LongTensor(atom_types),
            lengths=torch.Tensor(lengths).view(1, -1),
            angles=torch.Tensor(angles).view(1, -1),
            edge_index=torch.LongTensor(
                edge_indices.T
            ).contiguous(),  # shape (2, num_edges)
            to_jimages=torch.LongTensor(to_jimages),
            num_atoms=num_atoms,
            num_bonds=edge_indices.shape[0],
            num_nodes=num_atoms,  # special attribute used for batching in pytorch geometric
        )
        return data

    def __repr__(self) -> str:
        return f"TensorCrystDataset(len: {len(self.cached_data)})"


@hydra.main(config_path=str(PROJECT_ROOT / "conf"), config_name="default")
def main(cfg: omegaconf.DictConfig):
    from torch_geometric.data import Batch

    from cdvae.common.data_utils import get_scaler_from_data_list

    dataset: CrystDataset = hydra.utils.instantiate(
        cfg.data.datamodule.datasets.train, _recursive_=False
    )
    lattice_scaler = get_scaler_from_data_list(
        dataset.cached_data, key='scaled_lattice'
    )
    scaler = get_scaler_from_data_list(dataset.cached_data, key=dataset.prop)
    dataset.lattice_scaler = lattice_scaler
    dataset.scaler = scaler
    print(dataset)
    # -----------
    # print(dataset.lattice_scaler)
    # print(dataset.scaler)
    # print(dataset[0])
    # print(dataset[0].edge_index)
    # print(dataset[0].atom_types)

    data_list = [dataset[i] for i in range(len(dataset))]
    batch = Batch.from_data_list(data_list)
    return batch


if __name__ == "__main__":
    main()
