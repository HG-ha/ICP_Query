# -*- coding: utf-8 -*-
from siamese import Siamese
import cv2
from PIL import Image
import numpy as np
import onnxruntime as ort
import os
import sys
from load_config import config
from mlog import logger

class YOLO_ONNX:
    def __init__(self, model_path):
        providers = []
        if "CUDA" in config.captcha.device:
            providers.append("CUDAExecutionProvider")
        if "CPU" in config.captcha.device:
            providers.append("CPUExecutionProvider")
        if len(config.captcha.device) == 0 or len(providers) == 0:
            providers = ['CPUExecutionProvider']
        self.session = ort.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
    
    def extract_center_dominant_color_kmeans(self,image_input, output_path=None, k=2, color_tolerance=30):
        """
        使用K-means聚类提取中心区域主要颜色的改进版本
        
        Args:
            image_input: 输入图片路径(str) 或 cv2图像数组(numpy.ndarray)
            output_path: 输出图片路径
            k: K-means聚类数量
            color_tolerance: 颜色容差
        
        Returns:
            处理后的图像数组和主要颜色
        """
        # 读取或使用图像
        if isinstance(image_input, str):
            img = cv2.imread(image_input)
            if img is None:
                raise ValueError(f"无法读取图像: {image_input}")
        elif isinstance(image_input, np.ndarray):
            img = image_input.copy()
            if img.ndim == 3 and img.shape[-1] == 4:
                img = img[..., :3]
        else:
            raise ValueError("image_input 必须是图片路径(str)或cv2图像数组(numpy.ndarray)")
        
        height, width = img.shape[:2]
        
        # 提取中心1/3区域
        center_x, center_y = width // 2, height // 2
        region_width, region_height = width // 3, height // 3
        
        x1 = center_x - region_width // 2
        y1 = center_y - region_height // 2
        x2 = center_x + region_width // 2
        y2 = center_y + region_height // 2
        
        center_region = img[y1:y2, x1:x2]
        if center_region.size == 0:
            raise ValueError("中心区域为空，请检查图像大小")
        
        # 使用K-means聚类找到主要颜色
        center_pixels = center_region.reshape(-1, 3).astype(np.float32)
        
        # 确保有足够的像素进行聚类
        if center_pixels.shape[0] < k:
            k = max(1, center_pixels.shape[0])  # 调整k值为像素数量
        
        # 使用K-means聚类找到主要颜色
        center_pixels = center_region.reshape(-1, 3).astype(np.float32)
        
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, labels, centers = cv2.kmeans(center_pixels, k, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        # 找到最大的聚类（出现最多的颜色）
        unique_labels, counts = np.unique(labels, return_counts=True)
        dominant_cluster_idx = unique_labels[np.argmax(counts)]
        dominant_color = centers[dominant_cluster_idx].astype(int)
        # 创建掩码
        img_float = img.astype(np.float32)
        color_diff = np.sqrt(np.sum((img_float - dominant_color) ** 2, axis=2))
        mask = color_diff <= color_tolerance

        # === 噪点去除：形态学+小区域过滤 ===
        kernel = np.ones((1, 1), np.uint8)
        mask_clean = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel, iterations=1)
        mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_CLOSE, kernel, iterations=1)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_clean, connectivity=8)
        min_area = 20
        final_mask = np.zeros_like(mask_clean)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                final_mask[labels == i] = 1
        mask = final_mask.astype(bool)
        # === 噪点去除结束 ===

        # 根据图像通道数设置颜色
        if img.shape[2] == 4:  # RGBA或BGRA图像
            background_color = (255, 143, 0, 255)  # 添加alpha通道
            foreground_color = (255, 255, 255, 255)
        else:  # RGB或BGR图像
            background_color = (255, 143, 0)
            foreground_color = (255, 255, 255)
        
        # 创建结果图像
        result = np.full_like(img, background_color)
        result[mask] = foreground_color
        
        # 如果有两个以上的定点颜色不为background_color，则让前景色为白色，背景色为指定rgb色
        # 统计图像中的独特颜色
        unique_colors = np.unique(result.reshape(-1, result.shape[-1]), axis=0)
        
        # 统计不为background_color的颜色数量
        non_background_colors = []
        for color in unique_colors:
            if not np.array_equal(color, np.array(background_color)):
                non_background_colors.append(color)
        
        # 如果有两个以上的定点颜色不为background_color
        if len(non_background_colors) >= 2:
            # 重新设置颜色
            if img.shape[2] == 4:  # RGBA或BGRA图像
                new_foreground_color = (255, 255, 255, 255)  # 白色前景
                new_background_color = (255, 143, 0, 255)    # 指定RGB背景色
            else:  # RGB或BGR图像
                new_foreground_color = (255, 255, 255)       # 白色前景
                new_background_color = (255, 143, 0)         # 指定RGB背景色
            
            # 重新创建结果图像
            result = np.full_like(img, new_background_color)
            result[mask] = new_foreground_color
        
        # 轻度平滑抑制边缘毛刺
        result = cv2.medianBlur(result, 1)

        if output_path:
            cv2.imwrite(output_path, result)
        
        return result, dominant_color, mask

    def predict(self, source, boxes_only=False):
        confidence_thres = 0.5  # 定义置信度阈值
        iou_thres = 0.3  # 定义IOU阈值
        
        # 保持原始图像用于计算缩放比例
        img_height, img_width = source.shape[:2]
        
        # 预处理：BGR -> RGB -> resize -> normalize -> transpose -> expand_dims
        input_image = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
        res_image = cv2.resize(input_image, (512, 192))  # 注意：YOLO通常期望(width, height)
        if config.captcha.coding_show:
            # 保存一下原图
            cv2.imwrite(f"s_s.jpg", source)

        # 标准化到0-1范围
        input_image = res_image.astype(np.float32) / 255.0
        # 转换为CHW格式 (channels, height, width)
        input_image = np.transpose(input_image, (2, 0, 1))
        # 添加batch维度
        input_image = np.expand_dims(input_image, axis=0)
        
        outputs = self.session.run([self.output_name], {self.input_name: input_image})

        output = np.transpose(np.squeeze(outputs[0]))
        rows = output.shape[0]
        boxes, scores = [], []
        
        x_factor = img_width / 512
        y_factor = img_height / 192
        
        for i in range(rows):
            classes_scores = output[i][4:]
            max_score = np.amax(classes_scores)
            if (max_score >= confidence_thres) and (output[i][2] > 0) and (output[i][3] > 0):
                x, y, w, h = output[i][0], output[i][1], output[i][2], output[i][3]
                left = int((x - w / 2) * x_factor)
                top = int((y - h / 2) * y_factor)
                width = int(w * x_factor)
                height = int(h * y_factor)

                boxes.append([left, top, width, height])
                scores.append(max_score)
        
        if len(boxes) == 0:
            return (False, "未检测到目标") if not boxes_only else (False, "未检测到目标")
        

        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence_thres, iou_thres)
        
        if len(indices) == 0:
            return (False, "NMS后无有效检测结果") if not boxes_only else (False, "NMS后无有效检测结果")
            
        indices = indices.flatten().tolist()  # 解包索引
        
        new_boxes = [boxes[i] for i in indices]
        if len(new_boxes) < 4:
            logger.info(f"目标检测失败：检测到的框数量不足4个，实际数量为{len(new_boxes)}")
            return (False, "目标检测失败") if not boxes_only else (False, "目标检测失败")
        
        # 若只需要框，直接返回
        if boxes_only:
            return True, new_boxes
        
        cls_xy = []
        new_img = np.zeros_like(source)
        for box in new_boxes: 
            left, top, width, height = box 
            right = left + width 
            bottom = top + height
            try:
                box_mid_xy = [(left + width / 2) + 2,(top + height / 2)]
            except:
                box_mid_xy = [left + width / 2,top + height / 2]
            img = source[top:bottom, left:right]
            try:
                # 去干扰，去除失败则使用原图
                result, dominant_color, mask = self.extract_center_dominant_color_kmeans(
                    img,
                    k=8, 
                    color_tolerance=40
                )
                
                # 确保result和source的通道数一致
                if result.shape[2] != source.shape[2]:
                    if result.shape[2] == 3 and source.shape[2] == 4:
                        # 将3通道图像转换为4通道
                        result = cv2.cvtColor(result, cv2.COLOR_BGR2BGRA)
                    elif result.shape[2] == 4 and source.shape[2] == 3:
                        # 将4通道图像转换为3通道
                        result = cv2.cvtColor(result, cv2.COLOR_BGRA2BGR)
                
                if config.captcha.coding_show:
                    # 替换掉原图中的box区域
                    source[top:bottom, left:right] = result
                    new_img[top:bottom, left:right] = result
                data = {
                    "box_mid_xy": box_mid_xy,
                    "img":Image.fromarray(result)
                }
            except Exception as e:
                data = {
                        "box_mid_xy": box_mid_xy,
                        "img":Image.fromarray(img)
                    }
                
            cls_xy.append(data)
        
        if config.captcha.coding_show:
            cv2.imwrite(f"x_x.jpg", source)
            cv2.imwrite(f"n_n.jpg", new_img)
            for box in new_boxes:
                left, top, width, height = box 
                right = left + width 
                bottom = top + height
                cv2.rectangle(source, (left, top), (right, bottom), (0, 255, 0), 1)
        
        return True, cls_xy

def get_resource_path(relative_path):
    """获取打包后的可执行文件中的资源文件路径"""
    if getattr(sys, 'frozen', False):  # 如果是打包后的程序
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(app_path, relative_path)


class detnate:
    def __init__(self) -> None:
        self.comp_model = Siamese()
        self.det_model = YOLO_ONNX(model_path=get_resource_path('model_data/ibig.onnx'))
        self.small_selice_four_index = [
                [
                    {'x':163,'y':9},
                    {'x':193,'y':41}
                ],[
                    {'x':198,'y':9},
                    {'x':225,'y':41}
                ],[
                    {'x':230,'y':9},
                    {'x':259,'y':41}
                ],[
                    {'x':263,'y':9},
                    {'x':294,'y':41}
                ]
            ]
        

    def check_target(self,ibig,isma):
        success, ibig_result = self.det_model.predict(source=ibig)

        if not success:
            logger.info(f"目标检测失败：{ibig_result}")
            return False, ibig_result
        
        det_comp_result = []
        for i in self.small_selice_four_index:
            
            undet_sim = isma[i[0]['y']:i[1]['y'],i[0]['x']:i[1]['x']]
            undet_sim = cv2.cvtColor(undet_sim, cv2.COLOR_BGR2RGB)
            undet_sim = Image.fromarray(undet_sim)
            sim_big_comp = []
            for bigimg in ibig_result:
                undet_big = bigimg['img']
                det = self.comp_model.detect_image(undet_sim,undet_big)
                sim_big_comp.append([det.item(),bigimg['box_mid_xy']])

            max_value = float('-inf')
            max_coords = None
            save_max_coords = []
            de_coored = sim_big_comp.copy()
            for item in sim_big_comp:
                if item[0] > max_value:
                    max_value = item[0]
                    max_coords = item[1]
                    save_max_coords.append(item)

            if max_coords in det_comp_result:
                lbv = []
                for bv in de_coored:
                    if bv[1] not in det_comp_result:
                        lbv.append(bv[1])
                max_coords = lbv[0]

            det_comp_result.append(max_coords)
            
            if config.captcha.coding_show:
                text = str(self.small_selice_four_index.index(i) + 1)
                # 计算文本位置并进行边界检查
                text_x = max_coords[0] - 11
                text_y = max_coords[1] - 15
                
                # 确保文本不会绘制到图片外部
                img_height, img_width = ibig.shape[:2]
                text_x = max(0, min(text_x, img_width - 20))  # 预留文本宽度空间
                text_y = max(20, min(text_y, img_height - 5))  # 预留文本高度空间
                
                text_pos = (int(text_x), int(text_y))
                cv2.putText(ibig, text, text_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 3)
                cv2.putText(ibig, text, text_pos, cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
                if ibig.shape[2] != isma.shape[2]:
                    if ibig.shape[2] == 1:
                        ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
                    elif ibig.shape[2] == 4 and isma.shape[2] == 3:
                        isma = cv2.cvtColor(isma, cv2.COLOR_BGR2BGRA)
                    elif ibig.shape[2] == 3 and isma.shape[2] == 4:
                        ibig = cv2.cvtColor(ibig, cv2.COLOR_BGR2BGRA)
                    elif ibig.shape[2] == 3 and isma.shape[2] == 1:
                        isma = cv2.cvtColor(isma, cv2.COLOR_GRAY2BGR)
                    elif ibig.shape[2] == 1 and isma.shape[2] == 3:
                        ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
                width = min(ibig.shape[1], isma.shape[1]) 
                ibig_resized = cv2.resize(ibig, (width, int(ibig.shape[0] * (width / ibig.shape[1])))) 
                isma_resized = cv2.resize(isma, (width, int(isma.shape[0] * (width / isma.shape[1]))))
                new_image = np.vstack((ibig_resized, isma_resized))

        if config.captcha.coding_show:
            cv2.imwrite('coding_result.jpg', new_image)
            cv2.imshow('Coding result', new_image)
            def mouse_callback(event, x, y, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    print({"x":x,"y":y})
                    
            cv2.setMouseCallback('Coding result', mouse_callback)
            cv2.waitKey(0)
            cv2.destroyAllWindows()

        data = [{'x':int(i[0]),'y':int(i[1])} for i in det_comp_result]

        return True, data



if __name__ == "__main__":
    a = detnate()
    bigimg = cv2.imread('faile_captcha/ibig/d8600347-8e2a-4bf8-8f93-4cc0877099ab.jpg')
    smaimg = cv2.imread('faile_captcha/isma/d8600347-8e2a-4bf8-8f93-4cc0877099ab.jpg')

    print(a.check_target(bigimg,smaimg))