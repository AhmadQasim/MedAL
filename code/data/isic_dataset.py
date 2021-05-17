import os
import torchvision
from sklearn.model_selection import train_test_split
import numpy as np
from torchvision import transforms
from .dataset_utils import WeaklySupervisedDataset
from utils import TransformsSimCLR, TransformFix, oversampling_indices, merge, remove, k_medoids_init


class ISICDataset:
    def __init__(self, root, add_labeled=0, advanced_transforms=True, remove_classes=False,
                 expand_labeled=0, expand_unlabeled=0, unlabeled_subset_ratio=1, oversampling=True, stratified=False,
                 merged=True, unlabeled_augmentations=False, seed=9999, k_medoids=False, k_medoids_model=None,
                 k_medoids_n_clusters=10, start_labeled=300, benchmark_mode=True):
        self.root = root
        self.train_path = os.path.join(self.root, "isic", "train")
        self.test_path = os.path.join(self.root, "isic", "test")
        self.isic_mean = (0.6679, 0.5297, 0.5246)
        self.isic_std = (0.1338, 0.1470, 0.1577)
        self.input_size = 128
        self.crop_size = 128
        self.expand_labeled = expand_labeled
        self.expand_unlabeled = expand_unlabeled
        self.oversampling = oversampling
        self.stratified = stratified
        self.merged = merged
        self.merge_classes = []

        if advanced_transforms:
            self.transform_train = transforms.Compose([
                transforms.RandomCrop(self.crop_size),
                transforms.RandomAffine(degrees=90, translate=(0.2, 0.2)),
                transforms.Resize(size=self.input_size),
                transforms.RandomHorizontalFlip(),
                transforms.RandomVerticalFlip(),
                transforms.ToTensor(),
                transforms.RandomErasing(scale=(0.02, 0.2), ratio=(0.3, 0.9)),
            ])
            self.transform_test = transforms.Compose([
                transforms.Resize(size=self.input_size),
                transforms.ToTensor(),
            ])

        else:
            self.transform_train = transforms.Compose([
                transforms.Resize(size=self.input_size),
                transforms.ToTensor(),
            ])
            self.transform_test = transforms.Compose([
                transforms.Resize(size=self.input_size),
                transforms.ToTensor(),
            ])
        self.transform_autoencoder = transforms.Compose([
            transforms.RandomCrop(self.crop_size),
            transforms.RandomAffine(degrees=90, translate=(0.2, 0.2)),
            transforms.Resize(size=self.input_size),
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.ToTensor(),
            transforms.RandomErasing(scale=(0.02, 0.2), ratio=(0.3, 0.9)),
        ])
        self.transform_simclr = TransformsSimCLR(size=self.input_size)
        self.transform_fixmatch = TransformFix(crop_size=self.crop_size, input_size=self.input_size)
        self.merged_classes = 0 if self.merged else 0
        self.num_classes = 8 - self.merged_classes
        self.add_labeled = add_labeled
        self.unlabeled_subset_ratio = unlabeled_subset_ratio
        self.unlabeled_subset_num = None
        self.remove_classes = remove_classes
        self.unlabeled_augmentations = unlabeled_augmentations
        self.labeled_class_samples = None
        self.classes_to_remove = [2, 3, 4, 5, 6, 7]
        self.seed = seed
        self.labeled_amount = self.num_classes
        self.k_medoids = k_medoids
        self.k_medoids_model = k_medoids_model
        self.k_medoids_n_clusters = k_medoids_n_clusters
        self.start_labeled = start_labeled
        self.benchmark_mode = benchmark_mode

    def get_dataset(self):
        base_dataset = torchvision.datasets.ImageFolder(
            self.train_path, transform=None
        )

        test_dataset = torchvision.datasets.ImageFolder(
            self.test_path, transform=None
        )

        if self.merged and len(self.merge_classes) > 0:
            base_dataset = merge(base_dataset, self.merge_classes)
            test_dataset = merge(test_dataset, self.merge_classes)

        test_dataset = WeaklySupervisedDataset(test_dataset, range(len(test_dataset)),
                                               transform=self.transform_test,
                                               mean=self.isic_mean, std=self.isic_std)
        if self.benchmark_mode:
            idx = base_dataset.class_to_idx['unlabeled']
            imgs = np.array(base_dataset.imgs)
            unlabeled_indices = (imgs[:, 1] == str(idx)).nonzero()[0]
            labeled_indices = (~(imgs[:, 1] == str(idx))).nonzero()[0]
        else:
            if self.stratified:
                labeled_indices, unlabeled_indices = train_test_split(
                    np.arange(len(base_dataset)),
                    test_size=(len(base_dataset) - self.start_labeled) / len(base_dataset),
                    shuffle=True,
                    stratify=base_dataset.targets)
            else:
                if self.k_medoids:
                    labeled_indices, unlabeled_indices = k_medoids_init(base_dataset, self.k_medoids_model,
                                                                        self.transform_test, self.isic_mean,
                                                                        self.isic_std, self.seed, self.start_labeled,
                                                                        self.k_medoids_n_clusters)
                else:
                    indices = np.arange(len(base_dataset))
                    np.random.shuffle(indices)
                    labeled_indices, unlabeled_indices = indices[:self.start_labeled], indices[self.start_labeled:]

        self.unlabeled_subset_num = int(len(unlabeled_indices) * self.unlabeled_subset_ratio)

        self.labeled_class_samples = [np.sum(np.array(base_dataset.targets)[unlabeled_indices] == i)
                                      for i in range(len(base_dataset.classes))]

        if self.oversampling:
            labeled_indices = oversampling_indices(labeled_indices,
                                                   np.array(base_dataset.targets)[labeled_indices])

        if self.remove_classes and len(self.classes_to_remove) > 0:
            labeled_indices = labeled_indices[~np.isin(np.array(base_dataset.targets)[labeled_indices],
                                                       self.classes_to_remove)]

        labeled_dataset = WeaklySupervisedDataset(base_dataset, labeled_indices,
                                                  transform=self.transform_train,
                                                  poisson=True, seed=self.seed,
                                                  mean=self.isic_mean, std=self.isic_std)

        if self.unlabeled_augmentations:
            unlabeled_dataset = WeaklySupervisedDataset(base_dataset, unlabeled_indices,
                                                        transform=self.transform_train,
                                                        poisson=True, seed=self.seed,
                                                        mean=self.isic_mean, std=self.isic_std)
        else:
            unlabeled_dataset = WeaklySupervisedDataset(base_dataset, unlabeled_indices,
                                                        transform=self.transform_test,
                                                        mean=self.isic_mean, std=self.isic_std)

        return base_dataset, labeled_dataset, unlabeled_dataset, labeled_indices, unlabeled_indices, test_dataset

    def get_base_dataset_autoencoder(self):
        base_dataset = torchvision.datasets.ImageFolder(
            self.train_path, transform=None
        )

        '''
        if self.oversampling:
            base_indices = oversampling_indices(np.array(list(range(len(base_dataset)))),
                                                np.array(base_dataset.targets))
        else:
            base_indices = np.array(list(range(len(base_dataset))))
        '''

        if self.merged and len(self.merge_classes) > 0:
            base_dataset = merge(base_dataset, self.merge_classes)

        if self.remove_classes and len(self.classes_to_remove) > 0:
            base_dataset = remove(base_dataset, self.classes_to_remove)

        base_indices = np.array(list(range(len(base_dataset))))
        base_dataset = WeaklySupervisedDataset(base_dataset, base_indices, transform=self.transform_autoencoder,
                                               mean=self.isic_mean, std=self.isic_std)

        return base_dataset

    def get_base_dataset_simclr(self):
        base_dataset = torchvision.datasets.ImageFolder(
            self.train_path, transform=None
        )

        '''
        if self.oversampling:
            base_indices = oversampling_indices(np.array(list(range(len(base_dataset)))),
                                                np.array(base_dataset.targets))
        else:
            base_indices = np.array(list(range(len(base_dataset))))

        '''

        if self.merged and len(self.merge_classes) > 0:
            base_dataset = merge(base_dataset, self.merge_classes)

        if self.remove_classes and len(self.classes_to_remove) > 0:
            base_dataset = remove(base_dataset, self.classes_to_remove)

        base_indices = np.array(list(range(len(base_dataset))))
        base_dataset = WeaklySupervisedDataset(base_dataset, base_indices, transform=self.transform_simclr,
                                               mean=self.isic_mean, std=self.isic_std)

        return base_dataset

    def get_datasets_fixmatch(self, base_dataset, labeled_indices, unlabeled_indices):
        transform_labeled = transforms.Compose([
            transforms.RandomCrop(self.crop_size),
            transforms.RandomAffine(degrees=90, translate=(0.2, 0.2)),
            transforms.Resize(size=self.input_size),
            transforms.RandomHorizontalFlip(),
            transforms.RandomVerticalFlip(),
            transforms.ToTensor(),
            transforms.RandomErasing(scale=(0.02, 0.2), ratio=(0.3, 0.9)),
        ])

        expand_labeled = self.expand_labeled // len(labeled_indices)
        expand_unlabeled = self.expand_unlabeled // len(unlabeled_indices)
        labeled_indices = \
            np.hstack([labeled_indices for _ in range(expand_labeled)]) \
            if len(labeled_indices) < self.expand_labeled else labeled_indices
        unlabeled_indices = \
            np.hstack([unlabeled_indices for _ in range(expand_unlabeled)]) \
            if len(unlabeled_indices) < self.expand_unlabeled else unlabeled_indices

        if len(labeled_indices) < self.expand_labeled:
            diff = self.expand_labeled - len(labeled_indices)
            labeled_indices = np.hstack(
                (labeled_indices, np.random.choice(labeled_indices, diff)))

        if len(unlabeled_indices) < self.expand_unlabeled:
            diff = self.expand_unlabeled - len(unlabeled_indices)
            unlabeled_indices = np.hstack(
                (unlabeled_indices, np.random.choice(unlabeled_indices, diff)))

        labeled_dataset = WeaklySupervisedDataset(base_dataset, labeled_indices,
                                                  transform=transform_labeled,
                                                  poisson=True, seed=self.seed,
                                                  mean=self.isic_mean, std=self.isic_std)
        unlabeled_dataset = WeaklySupervisedDataset(base_dataset, unlabeled_indices,
                                                    transform=self.transform_fixmatch,
                                                    poisson=True, seed=self.seed,
                                                    mean=self.isic_mean, std=self.isic_std)

        return labeled_dataset, unlabeled_dataset
