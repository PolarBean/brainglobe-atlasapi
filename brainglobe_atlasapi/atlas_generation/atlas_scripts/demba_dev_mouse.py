from pathlib import Path

import numpy as np
import pooch
from brainglobe_utils.IO.image import load_any
from rich.progress import track
from scipy.ndimage import zoom

from brainglobe_atlasapi import BrainGlobeAtlas, utils
from brainglobe_atlasapi.atlas_generation.mesh_utils import (
    Region,
    create_region_mesh,
)
from brainglobe_atlasapi.atlas_generation.wrapup import wrapup_atlas_from_data
from brainglobe_atlasapi.structure_tree_util import get_structures_tree

# Copy-paste this script into a new file and fill in the functions to package
# your own atlas.

### Metadata ###

# The minor version of the atlas in the brainglobe_atlasapi, this is internal,
# if this is the first time this atlas has been added the value should be 0
# (minor version is the first number after the decimal point, ie the minor
# version of 1.2 is 2)
__version__ = 0

# The expected format is FirstAuthor_SpeciesCommonName, e.g. kleven_rat, or
# Institution_SpeciesCommonName, e.g. allen_mouse.
ATLAS_NAME = "demba_dev_mouse"

# DOI of the most relevant citable document
CITATION = "https://doi.org/10.1101/2024.06.14.598876"

# The scientific name of the species, ie; Rattus norvegicus
SPECIES = "Mus musculus"

# The URL for the data files
ATLAS_LINK = (
    "https://data.kg.ebrains.eu/zip?container=https://data-proxy.ebrains.eu/api/v1/\
        buckets/d-8f1f65bb-44cb-4312-afd4-10f623f929b8?prefix=interpolated_segmentations",
    "https://data.kg.ebrains.eu/zip?container=https://data-proxy.ebrains.eu/api/v1/\
        buckets/d-8f1f65bb-44cb-4312-afd4-10f623f929b8?prefix=interpolated_volumes",
)


# The orientation of the **original** atlas data, in BrainGlobe convention:
# https://brainglobe.info/documentation/setting-up/image-definition.html#orientation
ORIENTATION = "asr"

# The id of the highest level of the atlas. This is commonly called root or
# brain. Include some information on what to do if your atlas is not
# hierarchical
ROOT_ID = 997

# The resolution of your volume in microns. Details on how to format this
# parameter for non isotropic datasets or datasets with multiple resolutions.


RESOLUTION_TO_MODALITIES = {
    25: ["MRI", "LSFM"],
    10: ["ALLEN_STPT"],
    20: ["STPT"],
}


def download_resources(download_dir_path, atlas_file_url, ATLAS_NAME):

    utils.check_internet_connection()

    download_name = ATLAS_NAME
    destination_path = download_dir_path / download_name
    for afu in atlas_file_url:
        """
        Slight issue that the hash seems different each time. I think the
        files are being zipped on the server each time we request and it's
        changing the hash somehow (Maybe date and time is encoded in the
        file when zipped)
        """
        pooch.retrieve(
            url=afu,
            known_hash=None,
            path=destination_path,
            progressbar=True,
            processor=pooch.Unzip(extract_dir="."),
        )
    return destination_path


def retrieve_reference_and_annotation(download_dir_path, age, modality):
    """
    Retrieve the desired reference and annotation as two numpy arrays.

    Returns:
        tuple: A tuple containing two numpy arrays. The first array is the
        reference volume, and the second array is the annotation volume.
    """
    if modality == "STPT":
        reference_path = f"{download_dir_path}/demba_dev_mouse/\
            DeMBA_templates/DeMBA_P{age}_brain.nii.gz"
        annotation_path = f"{download_dir_path}/demba_dev_mouse/\
            AllenCCFv3_segmentations/20um/2022/\
                DeMBA_P{age}_segmentation_2022_20um.nii.gz"
    elif modality == "ALLEN_STPT":
        reference_path = f"{download_dir_path}/demba_dev_mouse/\
            allen_stpt_10um/DeMBA_P{age}_AllenSTPT_10um.nii.gz"
        annotation_path = f"{download_dir_path}/demba_dev_mouse/\
            AllenCCFv3_segmentations/10um/2022/\
            DeMBA_P{age}_segmentation_2022_10um.nii.gz"
    elif modality == "MRI":
        reference_path = f"{download_dir_path}/demba_dev_mouse/\
            mri_volumes/DeMBA_P{age}_mri.nii.gz"
        annotation_path = f"{download_dir_path}/demba_dev_mouse/\
            AllenCCFv3_segmentations/20um/2022/\
                DeMBA_P{age}_segmentation_2022_20um.nii.gz"
    elif modality == "LSFM":
        reference_path = f"{download_dir_path}/demba_dev_mouse/\
            lsfm_volumes/DeMBA_P{age}_lsfm.nii.gz"
        annotation_path = f"{download_dir_path}/demba_dev_mouse/\
            AllenCCFv3_segmentations/20um/2022/\
            DeMBA_P{age}_segmentation_2022_20um.nii.gz"
    annotation = load_any(annotation_path)
    reference = load_any(reference_path)
    if annotation.shape != reference.shape:
        """
        we unfortunately did not provide 25um segmentations so
        we will just downsample the 20um ones
        """
        zoom_factors = tuple(
            ref_dim / ann_dim
            for ref_dim, ann_dim in zip(reference.shape, annotation.shape)
        )
        annotation = zoom(annotation, zoom_factors, order=0)
    return reference, annotation


def retrieve_additional_references(download_dir_path, age, modalities):
    """This function only needs editing if the atlas has additional reference
    images. It should return a dictionary that maps the name of each
    additional reference image to an image stack containing its data.
    """
    additional_references = {}
    for modality in modalities:
        if modality == "STPT":
            reference_path = f"{download_dir_path}/demba_dev_mouse/\
                DeMBA_templates/DeMBA_P{age}_brain.nii.gz"
        elif modality == "ALLEN_STPT":
            reference_path = f"{download_dir_path}/demba_dev_mouse/\
                allen_stpt_10um/DeMBA_P{age}_AllenSTPT_10um.nii.gz"
        elif modality == "MRI":
            reference_path = f"{download_dir_path}/demba_dev_mouse/\
                mri_volumes/DeMBA_P{age}_mri.nii.gz"
        elif modality == "LSFM":
            reference_path = f"{download_dir_path}/demba_dev_mouse/\
                lsfm_volumes/DeMBA_P{age}_lsfm.nii.gz"
        ref = load_any(reference_path)
        additional_references[modality] = ref
    return additional_references


def retrieve_hemisphere_map():
    """
    Retrieve a hemisphere map for the atlas.

    If your atlas is asymmetrical, you may want to use a hemisphere map.
    This is an array in the same shape as your template,
    with 0's marking the left hemisphere, and 1's marking the right.

    If your atlas is symmetrical, ignore this function.

    Returns:
        numpy.array or None: A numpy array representing the hemisphere map,
        or None if the atlas is symmetrical.
    """
    return None


def retrieve_structure_information():
    """
    Retrieve the structures tree and meshes for the Allen mouse brain atlas.

    Returns:
        pandas.DataFrame: A DataFrame containing the atlas information.
    """
    # Since this atlas inherits from the allen can we not simply get the data
    # from the bgapi?
    print("determining structures")
    allen_atlas = BrainGlobeAtlas("allen_mouse_25um")
    allen_structures = allen_atlas.structures_list
    allen_structures = [
        {
            "id": i["id"],
            "name": i["name"],
            "acronym": i["acronym"],
            "structure_id_path": i["structure_id_path"],
            "rgb_triplet": i["rgb_triplet"],
        }
        for i in allen_structures
    ]
    return allen_structures


def retrieve_or_construct_meshes(
    structures, annotated_volume, download_dir_path
):
    """
    This function should return a dictionary of ids and corresponding paths to
    mesh files. We construct the meshes ourselves for this atlas, as the
    original data does not provide precomputed meshes.
    """
    print("constructing meshes")
    meshes_dir_path = download_dir_path / "meshes"
    meshes_dir_path.mkdir(exist_ok=True)
    tree = get_structures_tree(structures)
    labels = np.unique(annotated_volume).astype(np.int32)
    for key, node in tree.nodes.items():
        if key in labels:
            is_label = True
        else:
            is_label = False

        node.data = Region(is_label)

    # Mesh creation
    closing_n_iters = 2  # not used for this atlas
    decimate_fraction = 0.2  # not used for this atlas
    smooth = False
    for node in track(
        tree.nodes.values(),
        total=tree.size(),
        description="Creating meshes",
    ):
        create_region_mesh(
            (
                meshes_dir_path,
                node,
                tree,
                labels,
                annotated_volume,
                ROOT_ID,
                closing_n_iters,
                decimate_fraction,
                smooth,
            )
        )
    # Create meshes dict
    meshes_dict = dict()
    structures_with_mesh = []
    for s in structures:
        # Check if a mesh was created
        mesh_path = meshes_dir_path / f'{s["id"]}.obj'
        if not mesh_path.exists():
            print(f"No mesh file exists for: {s}, ignoring it")
            continue
        else:
            # Check that the mesh actually exists (i.e. not empty)
            if mesh_path.stat().st_size < 512:
                print(f"obj file for {s} is too small, ignoring it.")
                continue

        structures_with_mesh.append(s)
        meshes_dict[s["id"]] = mesh_path

    print(
        f"In the end, {len(structures_with_mesh)} "
        "structures with mesh are kept"
    )
    return meshes_dict


### If the code above this line has been filled correctly, nothing needs to be
### edited below (unless variables need to be passed between the functions).
if __name__ == "__main__":
    bg_root_dir = Path.home() / "brainglobe_workingdir" / ATLAS_NAME
    bg_root_dir.mkdir(exist_ok=True)
    download_resources(
        download_dir_path=bg_root_dir,
        ATLAS_NAME=ATLAS_NAME,
        atlas_file_url=ATLAS_LINK,
    )
    meshes_dict = None

    for age in range(4, 57):
        age_specific_root_dir = bg_root_dir / f"P{age}"
        age_specific_root_dir.mkdir(exist_ok=True)
        for resolution, modalities in RESOLUTION_TO_MODALITIES.items():
            reference_volume, annotated_volume = (
                retrieve_reference_and_annotation(
                    bg_root_dir, age, modalities[0]
                )
            )
            if len(modalities) > 1:
                additional_references = retrieve_additional_references(
                    bg_root_dir, age, modalities[1:]
                )
            hemispheres_stack = retrieve_hemisphere_map()
            structures = retrieve_structure_information()
            if meshes_dict is None:
                if resolution != 25:
                    raise (
                        """"
                        The order or resolutions is wrong,
                        25um should be first since its the most
                        efficient to produce (10um is far too slow)
                        """
                    )
                meshes_dict = retrieve_or_construct_meshes(
                    structures, annotated_volume, age_specific_root_dir
                )
            current_name = f"{ATLAS_NAME}_p{age}_{modalities[0]}"
            output_filename = wrapup_atlas_from_data(
                atlas_name=current_name,
                atlas_minor_version=__version__,
                citation=CITATION,
                atlas_link=ATLAS_LINK,
                species=SPECIES,
                resolution=(resolution,) * 3,
                orientation=ORIENTATION,
                root_id=ROOT_ID,
                reference_stack=reference_volume,
                annotation_stack=annotated_volume,
                structures_list=structures,
                meshes_dict=meshes_dict,
                working_dir=bg_root_dir,
                hemispheres_stack=None,
                cleanup_files=False,
                compress=True,
                scale_meshes=True,
                additional_references=additional_references,
            )
        meshes_dict = None
