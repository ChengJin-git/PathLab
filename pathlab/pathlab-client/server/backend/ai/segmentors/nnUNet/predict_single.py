import torch
from nnunetv2.inference.predict_from_raw_data import nnUNetPredictor


predictor = nnUNetPredictor(
    tile_step_size=0.5,
    use_gaussian=True,
    use_mirroring=True,
    perform_everything_on_device=True,
    device=torch.device('cuda', 1),
    verbose=False,
    verbose_preprocessing=False,
    allow_tqdm=True
)

model_folder = '/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d'
use_folds = ('all',) # (0, 1, 2, 3, 4) for ensemble of 5 models
checkpoint_name = 'checkpoint_best.pth'

predictor.initialize_from_trained_model_folder(
   model_folder,
    use_folds=use_folds,
    checkpoint_name=checkpoint_name,
)
# predictor.predict_from_files(join(nnUNet_raw, 'Dataset003_Liver/imagesTs'),
#                              join(nnUNet_raw, 'Dataset003_Liver/imagesTs_predlowres'),
#                              save_probabilities=False, overwrite=False,
#                              num_processes_preprocessing=2, num_processes_segmentation_export=2,
#                              folder_with_segs_from_prev_stage=None, num_parts=1, part_id=0)
#
# # predict a numpy array
# from nnunetv2.imageio.simpleitk_reader_writer import SimpleITKIO
#
# img, props = SimpleITKIO().read_images([join(nnUNet_raw, 'Dataset003_Liver/imagesTr/liver_63_0000.nii.gz')])
# ret = predictor.predict_single_npy_array(img, props, None, None, False)
#
# iterator = predictor.get_data_iterator_from_raw_npy_data([img], None, [props], None, 1)
# ret = predictor.predict_from_data_iterator(iterator, False, 1)

ret = predictor.predict_from_files_sequential(
    [['/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/imagesTs/TCGA-A2-A0D0-DX1_xmin68482_ymin39071_MPP-0.2500_0000.png'], 
     ['/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/imagesTs/TCGA-A2-A0SX-DX1_xmin53791_ymin56683_MPP-0.2500_0000.png']],
    '/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d/test_outputs', 
    save_probabilities=False, 
    overwrite=True, 
    folder_with_segs_from_prev_stage=None
)

