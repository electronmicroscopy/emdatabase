# Auto-generated stub file for emdatabase
from emdatabase.downloadable_dataset import DownloadableDataset

class AlNanocrystals(DownloadableDataset):
    """
    AlNanocrystals

    A 4D STEM dataset of Al nanocrystals on a carbon support.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class AmorphousFilm4nm4DSTEM(DownloadableDataset):
    """
    AmorphousFilm4nm4DSTEM

    A 4D-STEM dataset of a 4 nm amorphous thin film acquired with a 2.5 mrad probe on a Direct Electron CeleritasXS at 49000 fps. 256 x 256 probe positions (the central quarter of a 1024 x 1024 scan) of 128 x 128 pixel diffraction patterns. Both real and reciprocal space are calibrated - 0.12325 nm per scan step and 0.12453 1/nm per detector pixel, centred on the direct beam. Suitable for fluctuation electron microscopy and angular correlation analysis. Gain- and dark-corrected intensities were divided by 2 and rounded to uint16; multiply by 2 to recover ADU (the detector records 300 ADU per electron).

    DOI: 10.5281/zenodo.21632101

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/21632101/files


    """
    ...

class ApoferritinApollo15eps(DownloadableDataset):
    """
    ApoferritinApollo15eps

    A single cryo-EM movie of apoferritin from one stage position, collected at a 15 e-/pix/s dose rate on a Direct Electron Apollo. 76 unaligned, dark-subtracted counted super-resolution frames of 8192 x 8192 pixels at 0.2995 Angstrom per pixel, totalling 56.96 e-/Angstrom^2 (0.7495 e-/Angstrom^2 per frame). The super-resolution gain reference needed for frame correction is embedded in the file at metadata.Acquisition_instrument.TEM.Detector.gain_reference. Repackaged from EMPIAR-11254; see Peng et al., J Struct Biol X 7 (2022) 100080.

    DOI: 10.5281/zenodo.21632101

    License: CC0-1.0

    You can download this dataset here:
    https://zenodo.org/records/21632101/files


    """
    ...

class BilayerWS2(DownloadableDataset):
    """
    BilayerWS2

    small 4-D STEM dataset of a bilayer WS2. Each Diffraction pattern is only 8x8 pixels so the dataset is quite small although for simple non iterative ptychography 8x8 pixels should be sufficient.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class CuZnEELSMapping(DownloadableDataset):
    """
    CuZnEELSMapping

    An EELS spectrum image of copper and zinc oxide deposited on carbon nanotubes, used by the eXSpy elemental mapping tutorial. 40 x 50 probe positions at 0.9214 nm with 162 energy channels covering 700-1988 eV at 8 eV dispersion, which resolves the Cu-L2,3 (~931 eV) and Zn-L2,3 (~1020 eV) edges. The Zn:Cu ratio is 3:1 and roughly 80 wt% of the sample is carbon, so the edges sit on a large plasmon background - a good test case for model-based background removal and overlapping-edge quantification. The simultaneously acquired survey image is available as CuZnHAADF. Note - the Sample.description field in the file reads "Ta2O5 25% TiO2 CSIRO 400C", which is stale metadata carried over from an unrelated acquisition.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class CuZnHAADF(DownloadableDataset):
    """
    CuZnHAADF

    The HAADF survey image acquired simultaneously with the CuZnEELSMapping spectrum image - copper and zinc oxide on carbon nanotubes. 40 x 50 pixels at 0.9214 nm, uint16, on a JEOL ARM200F at 200 kV and 600000x. Pairs with CuZnEELSMapping for correlating elemental maps against the survey. Note - the Sample.description field in the file reads "Ta2O5 25% TiO2 CSIRO 400C", which is stale metadata carried over from an unrelated acquisition.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class FeAlStripes(DownloadableDataset):
    """
    FeAlStripes

    A 4D STEM dataset with FeAl stripes exhibiting magnetic stripes. The dataset can be used to study the correlation between structural and magnetic properties.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class HREBSDStrainPatterns(DownloadableDataset):
    """
    HREBSDStrainPatterns

    High-resolution EBSD patterns collected on a Direct Electron DE-Meridian, centred on a deformed region suitable for cross-correlation strain analysis. 32 x 32 probe positions at a 25 nm step, each pattern the sum of 256 counted, dark- and gain-corrected frames, binned 2 x 2 from 2048 x 2048 to 1024 x 1024 pixels. The pattern-plane geometry (detector distance, pattern centre, sample tilt) and the accelerating voltage were not recorded with the raw data, so the pattern axes are in detector pixels.

    DOI: 10.5281/zenodo.21632101

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/21632101/files


    """
    ...

class InSituElectrochemGrowth(DownloadableDataset):
    """
    InSituElectrochemGrowth

    An in-situ electrochemistry TEM movie showing growth in a liquid cell, recorded at 300 kV on a Direct Electron DE-Artemis in hardware counting mode. 245 frames of 4096 x 4096 pixels - every 4th frame of a 977 frame movie - with a calibrated 0.45448 nm pixel size and a 0.26208 s interval between saved frames (1.86 x 1.86 micron field of view, 64 s of elapsed time).

    DOI: 10.5281/zenodo.21632101

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/21632101/files


    """
    ...

class LSMOLineScan(DownloadableDataset):
    """
    LSMOLineScan

    A core-loss EELS line scan through a La(0.7)Sr(0.3)MnO3 thin film in which part of the film was deliberately given a very long electron beam exposure, inducing oxygen vacancies. Used by the eXSpy fine structure tutorial - the O-K and Mn-L2,3 fine structure changes measurably between the damaged and undamaged regions. 40 probe positions at 3.219 nm with 586 energy channels covering 428.5-721 eV at 0.5 eV dispersion. Acquired on a JEOL ARM200cF with a Gatan Quantum ER in DualEELS mode at 80 kV, 27.42 mrad convergence and 33.19 mrad collection angle. The matching low-loss spectrum is LSMOLineScanLowLoss.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class LSMOLineScanLowLoss(DownloadableDataset):
    """
    LSMOLineScanLowLoss

    The low-loss half of the DualEELS pair for LSMOLineScan - a La(0.7)Sr(0.3)MnO3 thin film line scan through a beam-damaged, oxygen-deficient region. 40 probe positions at 3.219 nm with 1024 energy channels covering -50 to 461.5 eV at 0.5 eV dispersion, containing the zero-loss peak and plasmon region. Use it with the core-loss spectrum for relative thickness mapping and Fourier-ratio deconvolution before fine structure analysis. Acquired on a JEOL ARM200cF with a Gatan Quantum ER at 80 kV.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class LSMOSTOLineScan(DownloadableDataset):
    """
    LSMOSTOLineScan

    A core-loss EELS line scan across a La(0.7)Sr(0.3)MnO3 thin film grown on SrTiO3, used by the eXSpy perovskite oxide analysis tutorial. 10 probe positions at 3.152 nm with 512 energy channels covering 395-906 eV at 1 eV dispersion, which contains the Ti-L2,3, O-K, Mn-L2,3 and La-M4,5 edges - so a single line scan crosses the interface and shows the Ti signal give way to La and Mn. Acquired on a JEOL ARM200cF with a Gatan Quantum ER in DualEELS mode at 200 kV, 27.1 mrad convergence and 33.1 mrad collection angle. The matching low-loss spectrum needed for thickness correction and Fourier-ratio deconvolution is LSMOSTOLineScanLowLoss. Binned from the original acquisition to keep the file small.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class LSMOSTOLineScanLowLoss(DownloadableDataset):
    """
    LSMOSTOLineScanLowLoss

    The low-loss half of the DualEELS pair for LSMOSTOLineScan - a La(0.7)Sr(0.3)MnO3 on SrTiO3 thin film line scan. 10 probe positions at 3.152 nm with 512 energy channels covering -50 to 461 eV at 1 eV dispersion, so it contains the zero-loss peak and the plasmon region. Use it with the core-loss spectrum for relative thickness mapping and Fourier-ratio deconvolution. Acquired on a JEOL ARM200cF with a Gatan Quantum ER at 200 kV; the low-loss dwell time is 9.44e-05 s against 0.4999 s for the core loss.

    License: Unspecified

    You can download this dataset here:
    https://raw.githubusercontent.com/hyperspy/exspy-demos/927d1f21b3b8aba4e2e622c2e621d3d9d5542d1c/EELS/datasets


    """
    ...

class LayeredCuNb4DSTEM(DownloadableDataset):
    """
    LayeredCuNb4DSTEM

    A 4D-STEM dataset of a layered Cu/Nb nanolaminate, acquired with a nearly parallel 1.58 mrad probe on a Direct Electron CeleritasXS. 128 x 128 probe positions (the central quarter of a 512 x 512 raster scan) of 256 x 256 pixel diffraction patterns, each the sum of 32 camera frames at 25000 fps. Reciprocal space is calibrated at 0.0078768 1/Angstrom per pixel and centred on the direct beam; the detector half-width is 1.008 1/Angstrom (25.3 mrad at 200 kV). The real-space scan step was not recorded by the scan controller, so the navigation axes are in pixels. Gain- and dark-corrected intensities were divided by 2 and rounded to uint16; multiply by 2 to recover ADU.

    DOI: 10.5281/zenodo.21632101

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/21632101/files


    """
    ...

class MgONanoCrystals(DownloadableDataset):
    """
    MgONanoCrystals

    A 4D STEM dataset of various MgO nanocrystals

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class NiEBSDLarge(DownloadableDataset):
    """
    NiEBSDLarge

    4125 EBSD patterns in a (55, 75) navigation shape of (60, 60) pixels from nickel, acquired on a NORDIF UF-1100 detector

    License: CC-BY-4.0

    You can download this dataset here:
    https://raw.githubusercontent.com/pyxem/kikuchipy-data/bcab8f7a4ffdb86a97f14e2327a4813d3156a85e/nickel_ebsd_large/


    """
    ...

class PdCuSiCrystallization(DownloadableDataset):
    """
    PdCuSiCrystallization

    A time resolved 4D-STEM series following the crystallization of a PdCuSi metallic glass, acquired on a Direct Electron CeleritasXS at 40000 fps with a 25 microsecond dwell time. 400 sequential scans of 47 x 39 probe positions (a 23.5 x 19.5 nm region cropped from a 256 x 256 scan) of 128 x 128 pixel diffraction patterns. Both real and reciprocal space are calibrated - 0.5 nm per scan step and 0.11 1/nm per detector pixel, centred on the direct beam. Successive scans are 1.6384 s apart and span 655.36 s of elapsed time, although the time axis is stored with a nm unit label. 24 GB of uint16 data uncompressed, chunked one time step at a time - the dataset used in the pyxem large data and lazy processing demo.

    DOI: 10.5281/zenodo.15490547

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class PdNiPGlass(DownloadableDataset):
    """
    PdNiPGlass

    A 4D STEM dataset of PdNiP metallic glass thin film.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class SPEDAg(DownloadableDataset):
    """
    SPEDAg

    A 4D STEM dataset of polycrystalline Ag including twins and grain boundaries.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

class TutorialUNet(DownloadableDataset):
    """
    TutorialUNet

    Trained weights for the small U-Net from the quantem tutorial neural_networks_02_unet.ipynb (quantem.core.ml.CNN2d, single-channel segmentation of synthetic shapes). A plain state dict saved with torch.save(model.state_dict(), path); load with torch.load(path, weights_only=True) into CNN2d(in_channels=1, out_channels=1, final_activation=torch.nn.Sigmoid()).

    License: MIT

    Model weights hosted at https://drive.google.com; see ``.versions`` for the dated snapshots.


    """
    ...

class ZrNbPrecipitate(DownloadableDataset):
    """
    ZrNbPrecipitate

    A 4D STEM dataset of ZrNb precipitate in ZrNb alloy.

    License: CC-BY-4.0

    You can download this dataset here:
    https://zenodo.org/records/15490547/files


    """
    ...

__all__ = ['AlNanocrystals', 'AmorphousFilm4nm4DSTEM', 'ApoferritinApollo15eps', 'BilayerWS2', 'CuZnEELSMapping', 'CuZnHAADF', 'FeAlStripes', 'HREBSDStrainPatterns', 'InSituElectrochemGrowth', 'LSMOLineScan', 'LSMOLineScanLowLoss', 'LSMOSTOLineScan', 'LSMOSTOLineScanLowLoss', 'LayeredCuNb4DSTEM', 'MgONanoCrystals', 'NiEBSDLarge', 'PdCuSiCrystallization', 'PdNiPGlass', 'SPEDAg', 'TutorialUNet', 'ZrNbPrecipitate']