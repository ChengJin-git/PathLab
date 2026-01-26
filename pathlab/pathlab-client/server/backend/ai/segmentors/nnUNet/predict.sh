# Set raw data path

input_fold="/storage/jmabq/data/nnUNet_Data/Dataset001_BCSS/imagesTs"
output_folder="/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d/predictions"
model_name="/storage/jmabq/data/nnUNet_Results/Dataset001_BCSS/nnUNetTrainer__nnUNetResEncUNetLPlans__2d"
checkpoint="checkpoint_best.pth"
device=cuda


CUDA_VISIBLE_DEVICES=2 nnUNetv2_predict_from_modelfolder -i $input_fold -o $output_folder/0 -m $model_name -f 0 -chk $checkpoint -device $device --save_probabilities &
CUDA_VISIBLE_DEVICES=6 nnUNetv2_predict_from_modelfolder -i $input_fold -o $output_folder/1 -m $model_name -f 1 -chk $checkpoint -device $device --save_probabilities &
CUDA_VISIBLE_DEVICES=5 nnUNetv2_predict_from_modelfolder -i $input_fold -o $output_folder/2 -m $model_name -f 2 -chk $checkpoint -device $device --save_probabilities &
CUDA_VISIBLE_DEVICES=4 nnUNetv2_predict_from_modelfolder -i $input_fold -o $output_folder/3 -m $model_name -f 3 -chk $checkpoint -device $device --save_probabilities &
CUDA_VISIBLE_DEVICES=3 nnUNetv2_predict_from_modelfolder -i $input_fold -o $output_folder/4 -m $model_name -f 4 -chk $checkpoint -device $device --save_probabilities &
wait

# ensemble predictions from multiple folds
nnUNetv2_ensemble -i [$output_folder/0,$output_folder/1,$output_folder/2,$output_folder/3,$output_folder/4] -o $output_folder/ensemble  