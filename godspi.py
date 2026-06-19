import cv2
import mediapipe as mp
import numpy as np
import collections
import time
from scipy.spatial import Voronoi
import os
import wave
import struct
import platform
import subprocess
import threading

# ================= 1. 物理音效合成与播放引擎 =================
def ensure_sound_files():
    """如果当前目录下没有音效文件，则用数学波形合成极其逼真的玻璃碎裂/爆炸音效和捏合特效音效"""
    shatter_filename = "glass_shatter.wav"
    pinch_filename = "pinch_effect.wav"
    sample_rate = 44100

    # 合成玻璃碎裂音效 (同之前代码)
    if not os.path.exists(shatter_filename):
        print("正在为您合成物理级玻璃碎裂音效，请稍候...")
        duration = 0.8
        num_samples = int(sample_rate * duration)
        noise = np.random.uniform(-1.0, 1.0, num_samples)
        t = np.linspace(0, duration, num_samples, endpoint=False)
        envelope = np.exp(-15 * t)
        envelope[:int(sample_rate*0.01)] = np.linspace(0, 1, int(sample_rate*0.01))
        noise[1:] = noise[1:] - 0.8 * noise[:-1]
        audio = noise * envelope
        for _ in range(15):
            delay = np.random.uniform(0.01, 0.4)
            delay_idx = int(delay * sample_rate)
            if delay_idx < num_samples:
                tinkle = np.random.uniform(-1.0, 1.0, num_samples - delay_idx)
                t_tinkle = np.linspace(0, duration-delay, num_samples - delay_idx, endpoint=False)
                env_tinkle = np.exp(-25 * t_tinkle)
                freq = np.random.uniform(4000, 9000)
                tinkle = tinkle * env_tinkle * np.sin(2 * np.pi * freq * t_tinkle)
                audio[delay_idx:] += tinkle * 0.5
        audio = audio / np.max(np.abs(audio))
        wav_file = wave.open(shatter_filename, 'w')
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
        for s in audio:
            s_int = max(-32768, min(32767, int(s * 32767.0)))
            wav_file.writeframes(struct.pack('h', s_int))
        wav_file.close()

    # 合成捏合特效音效 - 一段清脆的高频“嗡嗡”声
    if not os.path.exists(pinch_filename):
        print("正在为您合成捏合特效音效，请稍候...")
        duration = 1.2
        num_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, num_samples, endpoint=False)
        
        # 基础音调：随时间微微向上滑的高频正弦波
        freq_base = np.linspace(2500, 3000, num_samples)
        audio = 0.6 * np.sin(2 * np.pi * freq_base * t)
        
        # 加入一个包络，让声音慢慢变强，然后在结尾有一个小小的爆发
        envelope = np.ones_like(audio)
        envelope[:int(0.2*num_samples)] = np.linspace(0, 1, int(0.2*num_samples))
        envelope[-int(0.2*num_samples):] = np.linspace(1, 0, int(0.2*num_samples))
        audio *= envelope

        # 加入一个高频泛音，让声音更尖锐、更有“科幻”感
        freq_overtone = 2 * freq_base
        audio += 0.2 * np.sin(2 * np.pi * freq_overtone * t)

        # 归一化并写入文件
        audio = audio / np.max(np.abs(audio))
        wav_file = wave.open(pinch_filename, 'w')
        wav_file.setparams((1, 2, sample_rate, num_samples, 'NONE', 'not compressed'))
        for s in audio:
            s_int = max(-32768, min(32767, int(s * 32767.0)))
            wav_file.writeframes(struct.pack('h', s_int))
        wav_file.close()
        
    print("所有音效合成完毕！")

def play_sound(filename):
    """跨平台异步播放指定音效，不卡顿主画面"""
    sys_name = platform.system()
    def _play():
        try:
            if sys_name == 'Windows':
                import winsound
                winsound.PlaySound(filename, winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif sys_name == 'Darwin':
                subprocess.Popen(["afplay", filename])
            else:
                subprocess.Popen(["aplay", "-q", filename])
        except:
            pass
    threading.Thread(target=_play, daemon=True).start()


# ================= 2. 玻璃飞溅粒子系统 =================
class Particle:
    """模拟被打飞的玻璃渣 (同之前代码)"""
    def __init__(self, x, y):
        self.x = x
        self.y = y
        angle = np.random.uniform(0, 2 * np.pi)
        speed = np.random.uniform(20, 80)
        self.vx = np.cos(angle) * speed
        self.vy = np.sin(angle) * speed - 25 
        
        self.size = np.random.uniform(1.5, 6.0)
        self.gravity = 4.0   
        self.life = 1.0      
        self.decay = np.random.uniform(0.02, 0.06)
        
        self.pts = np.array([
            [np.random.uniform(-5, 5), np.random.uniform(-5, 5)] for _ in range(3)
        ], dtype=np.float32)
        
        c_val = np.random.randint(220, 255)
        self.color = (c_val, c_val, 255) 

    def update(self):
        """物理更新帧 (同之前代码)"""
        self.vy += self.gravity
        self.x += self.vx
        self.y += self.vy
        self.life -= self.decay
        
        theta = np.random.uniform(-0.5, 0.5)
        cos_t, sin_t = np.cos(theta), np.sin(theta)
        R = np.array([[cos_t, -sin_t], [sin_t, cos_t]])
        self.pts = np.dot(self.pts, R.T)

    def draw(self, img):
        if self.life > 0:
            scale = self.life * self.size
            pts_mapped = (self.pts * scale + np.array([self.x, self.y])).astype(np.int32)
            cv2.fillPoly(img, [pts_mapped], self.color)


# ================= 3. 预渲染 3D 物理裂纹引擎 =================
def generate_shatter_assets():
    """生成玻璃碎裂贴图素材 (同之前代码)"""
    print("正在生成 3A 级物理玻璃碎裂材质，请稍候...")
    W, H = 4000, 4000
    cx, cy = W // 2, H // 2
    
    pts = [[cx, cy]]
    num_radials = np.random.randint(18, 25)
    angles = np.linspace(0, 2 * np.pi, num_radials, endpoint=False) + np.random.rand(num_radials) * 0.2
    
    for angle in angles:
        for r in np.linspace(10, 2000, 80):
            r_jit = r + np.random.randn() * 15
            a_jit = angle + np.random.randn() * 0.02
            pts.append([cx + r_jit * np.cos(a_jit), cy + r_jit * np.sin(a_jit)])
            
    r = np.random.rand(1200)**1.5 * 2000
    theta = np.random.rand(1200) * 2 * np.pi
    pts.extend(np.column_stack((cx + r * np.cos(theta), cy + r * np.sin(theta))))
    
    vor = Voronoi(pts)
    crack_mask = np.zeros((H, W), dtype=np.uint8)
    for simplex in vor.ridge_vertices:
        if -1 not in simplex:
            p1 = vor.vertices[simplex[0]]
            p2 = vor.vertices[simplex[1]]
            if (0 <= p1[0] < W and 0 <= p1[1] < H) or (0 <= p2[0] < W and 0 <= p2[1] < H):
                thickness = 1 if np.random.rand() > 0.4 else 2
                cv2.line(crack_mask, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), 255, thickness)
                
    inv_mask = cv2.bitwise_not(crack_mask)
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(inv_mask, connectivity=4)
    
    shift_x_arr = np.zeros(num_labels, dtype=np.float32)
    shift_y_arr = np.zeros(num_labels, dtype=np.float32)
    for label in range(1, num_labels):
        dist = np.hypot(centroids[label][0] - cx, centroids[label][1] - cy)
        shift_amount = max(0, 60 - dist / 30)
        shift_x_arr[label] = (np.random.rand() - 0.5) * shift_amount
        shift_y_arr[label] = (np.random.rand() - 0.5) * shift_amount
        
    map_x_base = -shift_x_arr[labels]
    map_y_base = -shift_y_arr[labels]
    
    crack_mask_shifted = cv2.warpAffine(crack_mask, np.float32([[1, 0, 2], [0, 1, 2]]), (W, H))
    overlay = np.zeros((H, W, 3), dtype=np.uint8)
    overlay[crack_mask_shifted == 255] = [255, 255, 255]
    overlay[crack_mask == 255] = [40, 40, 40]
    
    overlay_mask = np.zeros((H, W), dtype=np.uint8)
    overlay_mask[crack_mask_shifted == 255] = 255
    overlay_mask[crack_mask == 255] = 255
    overlay_mask_inv = cv2.bitwise_not(overlay_mask)
    
    print("材质生成完毕！")
    return overlay, overlay_mask_inv, map_x_base, map_y_base


# ================= 4. 新增：双手手势识别引擎 =================
class DualHandGestureManager:
    """负责两只手的手势识别与状态转换"""
    def __init__(self):
        # 状态变量
        self.is_shattered_active = False           # 玻璃碎裂特效是否激活
        self.is_pinching_active = False          # 双手捏合特效是否激活
        self.pinch_start_time = 0                 # 捏合手势开始时间
        self.size_history = collections.deque(maxlen=3) # 用于出拳检测的双手尺寸历史

        # 出拳状态暂存
        self.last_punch_center = None
        self.last_punch_fist = False

        # 捏合状态暂存
        self.active_pinch_center = None           # 动态计算的两手之间中心点
        self.pinch_mask_params = None             # 动态计算的遮罩参数（椭圆长短轴）
        self.pixelation_level = 1.0               # 动态控制的像素化程度

    def update(self, results, w, h):
        """主更新循环，识别手势并转换状态"""
        has_hands = bool(results.multi_hand_landmarks)
        
        trigger_shatter = False
        max_hand_size = 0
        punch_center = None
        punch_fist = False
        
        hands_pinching = [] # 存储每只手是否是“捏合”状态

        # 优先处理两手捏合特效，它在持续进行中需要高优先级
        if self.is_pinching_active:
            self._update_pinching_state(results, w, h)
            # 如果手离开了，重置捏合状态
            if not has_hands or len(results.multi_hand_landmarks) < 2 or not all(hands_pinching):
                if time.time() - self.pinch_start_time > 0.5: # 给个短暂缓冲
                    self.is_pinching_active = False
            return trigger_shatter

        # —— 玻璃破碎检测阶段 ——
        if has_hands:
            for hand_landmarks in results.multi_hand_landmarks:
                # 处理单手信息
                wrist = hand_landmarks.landmark[0]
                mcp = hand_landmarks.landmark[9]
                wx, wy = wrist.x * w, wrist.y * h
                mx, my = mcp.x * w, mcp.y * h
                hand_size = np.hypot(wx - mx, wy - my)
                
                # 更新单手出拳爆发的候选信息
                if hand_size > max_hand_size:
                    max_hand_size = hand_size
                    punch_center = (int(mx), int(my))
                    punch_fist = self._is_fist(hand_landmarks, w, h)
                
                # 记录这只手是否在捏合
                hands_pinching.append(self._is_pinching(hand_landmarks, w, h))

        # 检查是否触发单手爆发
        if not self.is_pinching_active and not self.is_shattered_active:
            if max_hand_size > 0:
                self.size_history.append(max_hand_size)
                self.last_punch_center = punch_center
                self.last_punch_fist = punch_fist
                
                if len(self.size_history) >= 3:
                    current_size = self.size_history[-1]
                    oldest_size = self.size_history[0]
                    if punch_fist and current_size > w * 0.10 and (current_size - oldest_size) > w * 0.02:
                        trigger_shatter = True
            else:
                if len(self.size_history) >= 3:
                    current_size = self.size_history[-1]
                    oldest_size = self.size_history[0]
                    if self.last_punch_fist and current_size > w * 0.09 and (current_size - oldest_size) > w * 0.02:
                        trigger_shatter = True
                        punch_center = self.last_punch_center
                if not trigger_shatter:
                    self.size_history.clear()

        # —— 双手捏合检测阶段 ——
        # 如果检测到两只手都“捏合”，且在相互靠近
        if not self.is_shattered_active and has_hands and len(results.multi_hand_landmarks) >= 2:
            if all(hands_pinching) and not self.is_pinching_active:
                # 额外的判断：两手之间的中心点必须位于画面中心区域（像揪空气）
                l_hand_wrist = results.multi_hand_landmarks[0].landmark[0]
                r_hand_wrist = results.multi_hand_landmarks[1].landmark[0]
                center_x = (l_hand_wrist.x + r_hand_wrist.x) / 2
                center_y = (l_hand_wrist.y + r_hand_wrist.y) / 2
                
                # 判断中心是否在画面中心区域（30%-70%）
                if 0.3 < center_x < 0.7 and 0.3 < center_y < 0.7:
                    self.is_pinching_active = True
                    self.pinch_start_time = time.time()
                    play_sound("pinch_effect.wav")
                    # 初始化中心点和参数
                    self._update_pinching_state(results, w, h)
                    
        return trigger_shatter

    def _update_pinching_state(self, results, w, h):
        """动态更新双手捏合特效的参数"""
        if not results.multi_hand_landmarks or len(results.multi_hand_landmarks) < 2:
            return

        # 获取左手和右手的手指位置信息
        # MediaPipe 不保证 hand_landmarks[0] 一定是左手，但我们可以根据横坐标判断
        hand1 = results.multi_hand_landmarks[0]
        hand2 = results.multi_hand_landmarks[1]
        
        # 定义需要追踪的关键点索引：拇指尖(4), 食指尖(8)
        
        if hand1.landmark[0].x < hand2.landmark[0].x:
            left_hand = hand1
            right_hand = hand2
        else:
            left_hand = hand2
            right_hand = hand1
            
        # 1. 动态计算中心点：两手手腕中点
        l_wrist = left_hand.landmark[0]
        r_wrist = right_hand.landmark[0]
        self.active_pinch_center = (int((l_wrist.x + r_wrist.x)/2 * w), int((l_wrist.y + r_wrist.y)/2 * h))
        
        # 2. **核心逻辑**：动态控制范围和滤镜程度
        # 计算右手拇指和食指尖的距离（用于开合控制）
        r_thumb_tip = right_hand.landmark[4]
        r_index_tip = right_hand.landmark[8]
        # 使用手腕到中指 MCP 的距离作为参考，归一化手指开合度
        r_wrist = right_hand.landmark[0]
        r_middle_mcp = right_hand.landmark[9]
        ref_dist = np.hypot(r_wrist.x - r_middle_mcp.x, r_wrist.y - r_middle_mcp.y)
        
        finger_pinch_dist = np.hypot(r_thumb_tip.x - r_index_tip.x, r_thumb_tip.y - r_index_tip.y)
        # 归一化的开合度 (0.0=闭合，1.0=最大张开)
        opening_scale = min(1.0, finger_pinch_dist / (ref_dist * 1.5))
        
        # 动态遮罩范围参数：椭圆的长短轴
        # 张开度越大，椭圆越大
        min_axes = w * 0.05
        max_axes = w * 0.3
        axes_length = int(min_axes + opening_scale * (max_axes - min_axes))
        # axes_length 将用作橢圓的长轴和短轴，控制像素化区域的范围
        self.pinch_mask_params = axes_length
        
        # 动态像素化程度：张开度越小，像素越大（越模煳），反之亦然
        # 当手指完全张开，像素化程度降到最低，就像滤镜移开一样
        self.pixelation_level = 1.0 - opening_scale

    def _is_fist(self, hand_landmarks, w, h):
        """判断是否为握拳手势 (同之前代码)"""
        fingers = [(5, 8), (9, 12), (13, 16), (17, 20)]
        curled_count = 0
        wrist = hand_landmarks.landmark[0]
        for mcp_idx, tip_idx in fingers:
            mcp = hand_landmarks.landmark[mcp_idx]
            tip = hand_landmarks.landmark[tip_idx]
            dist_mcp = ((mcp.x * w - wrist.x * w)**2 + (mcp.y * h - wrist.y * h)**2)**0.5
            dist_tip = ((tip.x * w - wrist.x * w)**2 + (tip.y * h - wrist.y * h)**2)**0.5
            if dist_tip < dist_mcp * 1.2:
                curled_count += 1
        return curled_count >= 2

    def _is_pinching(self, hand_landmarks, w, h):
        """判断一只手是否为“捏合”状态（拇指和食指尖靠近）"""
        # 定义需要追踪的关键点索引：拇指尖(4), 食指尖(8)
        thumb_tip = hand_landmarks.landmark[4]
        index_tip = hand_landmarks.landmark[8]
        # MCP 点用于参考，判断其他手指是否未张开
        middle_mcp = hand_landmarks.landmark[9]
        wrist = hand_landmarks.landmark[0]
        
        # 计算拇指尖和食指尖的距离
        dist_pinch = np.hypot(thumb_tip.x * w - index_tip.x * w, thumb_tip.y * h - index_tip.y * h)
        # 归一化距离参考
        ref_dist = np.hypot(wrist.x * w - middle_mcp.x * w, wrist.y * h - middle_mcp.y * h)
        
        # 如果拇指和食指尖距离小于参考距离的某个比例
        return dist_pinch < ref_dist * 0.4


# ================= 5. 渲染引擎与滤镜系统 =================
class PixelationFilter:
    """负责创建动态范围的像素化特效遮罩"""
    def __init__(self, w, h):
        self.W = w
        self.H = h
        # 定义最小像素大小（最模煳状态）
        self.min_pixel_size = 20
        self.max_pixel_size = 3
        # 预先生成一个全是像素化版本的帧，以便高效处理

    def apply(self, img, center, axes_len, level):
        """应用动态遮罩像素化滤镜"""
        h, w, c = img.shape
        
        # —— 极速像素化主画面 ——
        # level从 0.0 (最模煳) 到 1.0 (最清晰)
        pixel_size = int(self.min_pixel_size - (level * (self.min_pixel_size - self.max_pixel_size)))
        pixel_size = max(self.max_pixel_size, pixel_size) # 限制最小像素

        small_h, small_w = h // pixel_size, w // pixel_size
        if small_h <= 0 or small_w <= 0: return img
        # 缩放至更小，然后用最近邻差值放大，实现像素化效果
        small_img = cv2.resize(img, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
        pixelated_img = cv2.resize(small_img, (w, h), interpolation=cv2.INTER_NEAREST)
        
        # —— 极速创建动态遮罩 ——
        mask = np.zeros((h, w), dtype=np.uint8)
        cx, cy = center
        # axes_len 控制椭圆大小，即像素化范围
        # axes_len = w * 0.2
        # 我们创建一个椭圆遮罩，axes_len既是椭圆的长轴也是短轴（变成圆）
        cv2.ellipse(mask, (cx, cy), (axes_len, axes_len), 0, 0, 360, 255, -1)
        
        # —— 极速遮罩混合 ——
        # 遮罩白色部分（捏合区域）显示像素化版本，黑色部分显示原始版本
        inv_mask = cv2.bitwise_not(mask)
        img_fg = cv2.bitwise_and(pixelated_img, pixelated_img, mask=mask)
        img_bg = cv2.bitwise_and(img, img, mask=inv_mask)
        
        result_img = cv2.add(img_fg, img_bg)
        
        # 在椭圆边缘加上一层动态的、微微发光的蓝色边缘线
        alpha = level # 强度也随手指开合动态变化
        b_val = int(255 * alpha)
        c_val = int(100 * alpha)
        color = (b_val, c_val, c_val) # 青蓝色
        line_thickness = 3
        cv2.ellipse(result_img, (cx, cy), (axes_len, axes_len), 0, 0, 360, color, line_thickness)
        
        return result_img


# ===================== 主程序启动 =====================
# 初始化
ensure_sound_files()  # 初始化音效
overlay_base, overlay_mask_inv_base, map_x_base, map_y_base = generate_shatter_assets()

mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# —— 重要修改：max_num_hands=2 ——
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,         
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# 初始化双手手势管理器和滤镜
gesture_manager = DualHandGestureManager()
pixel_filter = None # 将在获取第一帧后初始化

cap = cv2.VideoCapture(0)
# cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280) # 如果摄像头支持，提高分辨率
# cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("\n>>> 程序已启动。")
print("1. 快速向摄像头出拳触发爆裂特效！")
print("2. 两只手同时向画面中间“揪住空气”触发动态像素化滤镜，用手指开合控制范围和程度！")
print("按 'ESC' 键退出...")

# 特效维持状态变量
shatter_particles = []
X_grid, Y_grid = None, None
shatter_assets = {}

while cap.isOpened():
    success, image = cap.read()
    if not success:
        break

    image = cv2.flip(image, 1)
    h, w, c = image.shape
    
    if pixel_filter is None:
        pixel_filter = PixelationFilter(w, h)
    
    if X_grid is None or X_grid.shape != (h, w):
        X_grid, Y_grid = np.meshgrid(np.arange(w), np.arange(h))
        X_grid = X_grid.astype(np.float32)
        Y_grid = Y_grid.astype(np.float32)
    
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    image_rgb.flags.writeable = False
    results = hands.process(image_rgb)
    image_rgb.flags.writeable = True
    image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    # 在未触发持续特效时绘制手骨骼
    if results.multi_hand_landmarks and not gesture_manager.is_pinching_active:
        for hand_landmarks in results.multi_hand_landmarks:
            mp_drawing.draw_landmarks(
                image, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                mp_drawing_styles.get_default_hand_landmarks_style(),
                mp_drawing_styles.get_default_hand_connections_style()
            )

    # —— 核心修改：使用 DualHandGestureManager ——
    if not gesture_manager.is_shattered_active and not gesture_manager.is_pinching_active:
        trigger_shatter = gesture_manager.update(results, w, h)

        # —— 触发：玻璃爆发爆发特特效 ——
        if trigger_shatter:
            gesture_manager.is_shattered_active = True
            gesture_manager.pinch_start_time = time.time() # 使用 pinch_start_time 作为统一的特效计时
            play_sound("glass_shatter.wav")
            
            px, py = gesture_manager.last_punch_center
            shatter_particles = [Particle(px, py) for _ in range(100)] 
            
            startX = max(0, 2000 - px)
            startY = max(0, 2000 - py)
            shatter_assets = {
                'overlay': overlay_base[startY:startY+h, startX:startX+w],
                'mask_inv': overlay_mask_inv_base[startY:startY+h, startX:startX+w],
                'map_x': map_x_base[startY:startY+h, startX:startX+w],
                'map_y': map_y_base[startY:startY+h, startX:startX+w]
            }
            # 预计算最终映射
            shatter_assets['final_map_x'] = X_grid + shatter_assets['map_x']
            shatter_assets['final_map_y'] = Y_grid + shatter_assets['map_y']
            
    elif gesture_manager.is_pinching_active:
        # 特效进行中，持续更新参数
        gesture_manager.update(results, w, h)

    # == 应用渲染视觉特效 ==
    # 状态一：玻璃破碎爆发（单手爆发持续时间短，且不可连续触发）
    if gesture_manager.is_shattered_active:
        elapsed = time.time() - gesture_manager.pinch_start_time
        if elapsed < 3.0: 
            # 【特效：屏幕剧烈震动】 (同之前代码)
            shake_duration = 0.5 
            intensity = int(50 * (1.0 - elapsed / shake_duration)) if elapsed < shake_duration else 0
            dx, dy = (np.random.randint(-intensity, intensity + 1), np.random.randint(-intensity, intensity + 1)) if intensity > 0 else (0, 0)
            
            # 【特效：光学畸变与裂纹贴图】
            image = cv2.remap(image, shatter_assets['final_map_x'] + dx, shatter_assets['final_map_y'] + dy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            image = cv2.bitwise_and(image, image, mask=shatter_assets['mask_inv'])
            image = cv2.add(image, shatter_assets['overlay'])
            
            # 【特效：满屏玻璃渣飞溅粒子】
            for p in shatter_particles:
                p.update()
                p.draw(image)
        else:
            gesture_manager.is_shattered_active = False # 时间到，特效重置
            gesture_manager.size_history.clear()

    # **状态二：双手捏合动态像素化滤镜 (持续模式)**
    elif gesture_manager.is_pinching_active:
        # 特效持续进行，由手势管理器动态计算出的参数决定画面
        # 1. 动态中心点：axes_center
        # 2. 动态范围：axes_len
        # 3. 动态像素程度：pixel_level
        
        # axes_len = int(np.hypot(w, h)) if gesture_manager.pinch_mask_params is None else gesture_manager.pinch_mask_params
        axes_len = gesture_manager.pinch_mask_params
        axes_center = gesture_manager.active_pinch_center
        pixel_level = gesture_manager.pixelation_level
        
        # 应用动态遮罩像素化滤镜
        image = pixel_filter.apply(image, axes_center, axes_len, pixel_level)
        
    cv2.imshow('Hand Skeleton Tracking', image)

    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()