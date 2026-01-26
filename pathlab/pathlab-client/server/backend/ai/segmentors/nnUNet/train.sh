# Set raw data path
export nnUNet_raw="/storage/jmabq/data/nnUNet_Data"
# Set preprocessed data path
export nnUNet_preprocessed="/storage/jmabq/data/nnUNet_Preprocessed"
# Set results path
export nnUNet_results="/storage/jmabq/data/nnUNet_Results"

# You can choose from [nnUNetPlannerResEncM, nnUNetPlannerResEncL, nnUNetPlannerResEncXL]
plan="nnUNetPlannerResEncL"
task_id=1
dataset_name="Dataset001_BCSS"

# DO NOT Modify the below line
plan_mapper=${plan/PlannerResEnc/ResEncUNet}Plans

# generate plans and preprocess the data, call it at the beginning only once
# nnUNetv2_plan_and_preprocess -d $task_id -pl $plan  --verify_dataset_integrity

# Train a model
CUDA_VISIBLE_DEVICES=2 nnUNetv2_train $dataset_name 2d 0 -p $plan_mapper -device 'cuda' &
CUDA_VISIBLE_DEVICES=6 nnUNetv2_train $dataset_name 2d 1 -p $plan_mapper -device 'cuda' &
CUDA_VISIBLE_DEVICES=5 nnUNetv2_train $dataset_name 2d 2 -p $plan_mapper -device 'cuda' &
CUDA_VISIBLE_DEVICES=4 nnUNetv2_train $dataset_name 2d 3 -p $plan_mapper -device 'cuda' &
CUDA_VISIBLE_DEVICES=3 nnUNetv2_train $dataset_name 2d 4 -p $plan_mapper -device 'cuda' &
wait