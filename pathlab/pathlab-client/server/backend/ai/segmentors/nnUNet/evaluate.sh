gt_folder="/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/labelsTs"
pred_folder="/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d/predictions/4"
output_file="/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d/evaluation.json"
dataset_json="/storage/jmabq/data/nnUNet_Preprocessed/Dataset001_BCSS/dataset.json"
plan_json="/storage/jmabq/data/nnUNet_Preprocessed/Dataset001_BCSS/nnUNetResEncUNetLPlans.json"

nnUNetv2_evaluate_folder $gt_folder $pred_folder -o $output_file -djfile $dataset_json -pfile $plan_json