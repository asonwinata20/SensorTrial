import kivy
from kivy.config import Config
Config.set('graphics', 'width', '1280')
Config.set('graphics', 'height', '720')
Config.set('graphics', 'resizable', False)

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, Line
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

import threading
import queue
import os    
import csv   
import time  
from collections import deque

from sensor_backmatter import SensorAcquisitionWorker

class TelemetryDashboard(App):
    def build(self):
        self.telemetry_queue = queue.Queue()
        self.points_count = 100 
        
        # 14 Channels total
        self.buffers = [deque([0.0] * self.points_count, maxlen=self.points_count) for _ in range(14)]
        
        # Split Peak Memory arrays (Flex uses floats, EMG uses ints)
        self.flex_peaks = [0.0] * 5
        self.emg_peaks = [0] * 3
        
        self.is_recording = False
        self.session_data_log = []
        self.recording_start_time = 0.0
        
        # 📂 Absolute path mapping to enforce target root folder visibility on Pi OS
        self.project_directory = os.path.dirname(os.path.abspath(__file__))
        
        root_layout = BoxLayout(orientation='horizontal', spacing=5)
        with root_layout.canvas.before:
            Color(0.09, 0.09, 0.10, 1)
            self.bg_rect = Rectangle(size=(1280, 720), pos=(0, 0))
        root_layout.bind(size=self.update_rect, pos=self.update_rect)

        # CONTROL SIDEBAR
        sidebar = BoxLayout(orientation='vertical', size_hint=(0.20, 1), padding=12, spacing=15)
        with sidebar.canvas.before:
            Color(0.14, 0.15, 0.17, 1)
            self.sidebar_bg = Rectangle()
        sidebar.bind(size=self.update_sidebar_bg, pos=self.update_sidebar_bg)

        sidebar_title = Label(text="SYSTEM CONTROL", font_size='16sp', bold=True, size_hint=(1, 0.1))
        sidebar.add_widget(sidebar_title)

        self.btn_start = Button(text="Start Stream", font_size='14sp', size_hint=(1, 0.1))
        self.btn_stop = Button(text="Stop Stream", font_size='14sp', size_hint=(1, 0.1), disabled=True)
        self.btn_check = Button(text="Check Hardware", font_size='14sp', size_hint=(1, 0.1), background_color=(0.2, 0.5, 0.7, 1))
        self.btn_reset = Button(text="Reset Dashboard", font_size='14sp', size_hint=(1, 0.1), background_color=(0.7, 0.3, 0.3, 1))
        
        self.lbl_status_indicator = Label(text="STATUS: IDLE", font_size='12sp', bold=True, size_hint=(1, 0.08), color=(0.6, 0.6, 0.6, 1))
        
        self.btn_start.bind(on_press=self.start_stream)
        self.btn_stop.bind(on_press=self.stop_stream)
        self.btn_check.bind(on_press=self.trigger_i2c_check)
        self.btn_reset.bind(on_press=self.reset_entire_dashboard)
        
        sidebar.add_widget(self.btn_start)
        sidebar.add_widget(self.btn_stop)
        sidebar.add_widget(self.btn_check)
        sidebar.add_widget(self.btn_reset)
        sidebar.add_widget(self.lbl_status_indicator)
        sidebar.add_widget(Label(size_hint=(1, 0.42)))
        root_layout.add_widget(sidebar)

        # MAIN WORKSPACE AREA
        right_workspace = BoxLayout(orientation='vertical', size_hint=(0.80, 1), padding=12, spacing=8)
        
        scroll_window = ScrollView(size_hint=(1, 0.75), do_scroll_x=False, do_scroll_y=True)
        dashboard_grid = GridLayout(cols=3, spacing=10, size_hint_y=None)
        dashboard_grid.bind(minimum_height=dashboard_grid.setter('height'))
        
        graph_meta = [
            {"label": "F1 - THUMB (V)", "color": (1, 0.2, 0.2, 1)},
            {"label": "F2 - INDEX (V)", "color": (1, 0.6, 0.1, 1)},
            {"label": "F3 - MIDDLE (V)", "color": (1, 0.9, 0.1, 1)},
            {"label": "F4 - RING (V)", "color": (0.2, 0.9, 0.2, 1)},
            {"label": "F5 - PINKY (V)", "color": (0.1, 0.7, 1, 1)},
            {"label": "EMG 1 (RAW)", "color": (1, 0.1, 1, 1)},
            {"label": "EMG 2 (RAW)", "color": (0.8, 0.2, 1, 1)},
            {"label": "EMG 3 (RAW)", "color": (0.5, 0.4, 1, 1)},
            {"label": "ACCELEROMETER - X (g)", "color": (0.3, 0.9, 0.6, 1)},
            {"label": "ACCELEROMETER - Y (g)", "color": (0.8, 0.4, 1, 1)},
            {"label": "ACCELEROMETER - Z (g)", "color": (0.9, 0.8, 0.6, 1)},
            {"label": "GYROSCOPE - X (dps)", "color": (0.4, 0.7, 1, 1)},
            {"label": "GYROSCOPE - Y (dps)", "color": (0.7, 0.4, 1, 1)},
            {"label": "GYROSCOPE - Z (dps)", "color": (1, 0.4, 0.7, 1)}
        ]
        
        self.graph_areas = []
        self.plot_lines = []
        self.plot_bgs = []
        
        for meta in graph_meta:
            card = BoxLayout(orientation='vertical', padding=4, size_hint_y=None, height=170)
            card_title = Label(text=meta["label"], font_size='11sp', bold=True, size_hint=(1, 0.15), halign='left')
            card_title.bind(size=card_title.setter('text_size'))
            
            plot_box = BoxLayout(size_hint=(1, 0.85))
            with plot_box.canvas.before:
                Color(0.05, 0.05, 0.06, 1)
                bg_rect = Rectangle()
                self.plot_bgs.append(bg_rect)
            with plot_box.canvas.after:
                Color(*meta["color"])
                line_trace = Line(width=1.8, points=[])
                self.plot_lines.append(line_trace)
                
            card.add_widget(card_title)
            card.add_widget(plot_box)
            dashboard_grid.add_widget(card)
            
            self.graph_areas.append(plot_box)
            
        scroll_window.add_widget(dashboard_grid)
        right_workspace.add_widget(scroll_window)
        
        # Lower Telemetry Console Display Panel
        data_panel = BoxLayout(orientation='horizontal', size_hint=(1, 0.25), padding=10, spacing=10)
        with data_panel.canvas.before:
            Color(0.12, 0.13, 0.15, 1)
            self.panel_bg = Rectangle()
        data_panel.bind(size=self.update_panel_bg, pos=self.update_panel_bg)
        
        # Flex labels track Volts
        self.lbl_hand_data = Label(
            text="FLEX TRACKING (CURRENT / PEAK):\nF1: --V (--V) | F2: --V (--V) | F3: --V (--V)\nF4: --V (--V) | F5: --V (--V)",
            font_size='12sp', bold=True, halign='left', valign='middle', color=(0.9, 0.9, 0.9, 1)
        )
        self.lbl_hand_data.bind(size=self.lbl_hand_data.setter('text_size'))
        
        # 🛠️ SANITIZED: Removed all 'V' characters from the EMG readout strings
        self.lbl_emg_data = Label(
            text="EMG PROFILES (CURRENT / PEAK):\nEMG1: -- (--)\nEMG2: -- (--)\nEMG3: -- (--)",
            font_size='12sp', bold=True, halign='left', valign='middle', color=(1.0, 0.4, 1.0, 1)
        )
        self.lbl_emg_data.bind(size=self.lbl_emg_data.setter('text_size'))
        
        self.lbl_motion_data = Label(
            text="6-AXIS IMU METRICS:\nACC: X:--g | Y:--g | Z:--g\nGYR: X:--dps | Y:--dps | Z:--dps",
            font_size='12sp', bold=True, halign='left', valign='middle', color=(0.0, 0.8, 1.0, 1)
        )
        self.lbl_motion_data.bind(size=self.lbl_motion_data.setter('text_size'))
        
        data_panel.add_widget(self.lbl_hand_data)
        data_panel.add_widget(self.lbl_emg_data)
        data_panel.add_widget(self.lbl_motion_data)
        right_workspace.add_widget(data_panel)
        
        root_layout.add_widget(right_workspace)
        return root_layout

    def on_start(self):
        self.worker = SensorAcquisitionWorker(self.telemetry_queue)
        self.worker_thread = threading.Thread(target=self.worker.main_loop)
        self.worker_thread.daemon = True
        self.worker_thread.start()
        Clock.schedule_interval(self.update_telemetry_ui, 0.016)

    def start_stream(self, instance):
        self.session_data_log.clear()
        self.recording_start_time = time.time()
        self.is_recording = True
        
        self.worker.is_streaming = True
        self.btn_start.disabled = True
        self.btn_stop.disabled = False
        self.lbl_status_indicator.text = "STATUS: RECORDING"
        self.lbl_status_indicator.color = (1, 0.3, 0.3, 1)

    def stop_stream(self, instance):
        self.worker.is_streaming = False
        self.btn_start.disabled = False
        self.btn_stop.disabled = True
        
        self.is_recording = False
        self.save_recorded_session_to_csv()

    # --- 📂 AUTOMATED FILE SYSTEM EXPORT ENGINE (ABSOLUTE WORKSPACE MOUNT) ---
    def save_recorded_session_to_csv(self):
        if not self.session_data_log:
            self.lbl_status_indicator.text = "STATUS: NO DATA"
            self.lbl_status_indicator.color = (0.6, 0.6, 0.6, 1)
            return

        self.lbl_status_indicator.text = "STATUS: SAVING..."
        self.lbl_status_indicator.color = (1, 1, 0.3, 1)

        # ⚡ ABSOLUTE PI COMPILATION CHECK: Scan using full absolute paths
        counter = 1
        while True:
            check_path = os.path.join(self.project_directory, f"emgimuflex-data_{counter}.csv")
            if not os.path.exists(check_path):
                break
            counter += 1
            
        target_filename = f"emgimuflex-data_{counter}.csv"
        absolute_export_path = os.path.join(self.project_directory, target_filename)

        try:
            with open(absolute_export_path, mode='w', newline='') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow([
                    'Relative_Time_Sec', 
                    'Flex_1_V', 'Flex_2_V', 'Flex_3_V', 'Flex_4_V', 'Flex_5_V',
                    'EMG_1_Raw', 'EMG_2_Raw', 'EMG_3_Raw',
                    'Accel_X', 'Accel_Y', 'Accel_Z',
                    'Gyro_X', 'Gyro_Y', 'Gyro_Z'
                ])
                writer.writerows(self.session_data_log)
                
            print(f"📝 Data exported safely to absolute repository destination -> {absolute_export_path}")
            self.lbl_status_indicator.text = f"SAVED: _{counter}.csv"
            self.lbl_status_indicator.color = (0.3, 1, 0.3, 1)
        except Exception as e:
            print(f"❌ Error writing CSV file to disk: {e}")
            self.lbl_status_indicator.text = "STATUS: WRITE ERR"
            self.lbl_status_indicator.color = (1, 0.3, 0.3, 1)

        self.session_data_log.clear()

    def reset_entire_dashboard(self, instance):
        self.buffers = [deque([0.0] * self.points_count, maxlen=self.points_count) for _ in range(14)]
        self.flex_peaks = [0.0] * 5
        self.emg_peaks = [0] * 3
        
        self.lbl_hand_data.text = (
            f"FLEX SENSORS (NOW / MAX):\n"
            f"F1: 0.00V (0.00V) | F2: 0.00V (0.00V)\n"
            f"F3: 0.00V (0.00V) | F4: 0.00V (0.00V)\n"
            f"F5: 0.00V (0.00V)"
        )
        self.lbl_emg_data.text = (
            f"EMG PROFILES (NOW / MAX):\n"
            f"EMG1: 0 (0)\n"
            f"EMG2: 0 (0)\n"
            f"EMG3: 0 (0)"
        )
        self.lbl_motion_data.text = (
            f"6-AXIS IMU METRICS:\n"
            f"ACC: X:+0.00g | Y:+0.00g | Z:+0.00g\n"
            f"GYR: X:+0000 | Y:+0000 | Z:+0000"
        )
        self.redraw_grid_waveforms()

    def trigger_i2c_check(self, instance):
        _, status_msg = self.worker.check_i2c_status()
        content = BoxLayout(orientation='vertical', padding=15, spacing=15)
        close_btn = Button(text="Dismiss", size_hint=(1, 0.3))
        content.add_widget(Label(text=status_msg, font_size='15sp', halign='center'))
        content.add_widget(close_btn)
        popup = Popup(title="🎛️ Hardware Scan Pass", content=content, size_hint=(0.55, 0.42))
        close_btn.bind(on_press=popup.dismiss)
        popup.open()

    def update_telemetry_ui(self, dt):
        has_new_data = False
        latest_f, latest_emg, latest_a, latest_g = None, None, None, None

        while True:
            try:
                frame = self.telemetry_queue.get_nowait()
                latest_f = frame['flex']
                latest_emg = frame['emg']
                latest_a = frame['accel']
                latest_g = frame['gyro']
                
                for i in range(5):
                    if latest_f[i] > self.flex_peaks[i]: self.flex_peaks[i] = latest_f[i]
                    self.buffers[i].append(latest_f[i])
                    
                for i in range(3):
                    if latest_emg[i] > self.emg_peaks[i]: self.emg_peaks[i] = latest_emg[i]
                    self.buffers[5 + i].append(latest_emg[i])
                    
                for i in range(3): self.buffers[8 + i].append(latest_a[i])
                for i in range(3): self.buffers[11 + i].append(latest_g[i])
                
                if self.is_recording:
                    relative_timestamp = time.time() - self.recording_start_time
                    row_entry = [
                        f"{relative_timestamp:.4f}", 
                        latest_f[0], latest_f[1], latest_f[2], latest_f[3], latest_f[4],
                        latest_emg[0], latest_emg[1], latest_emg[2],
                        latest_a[0], latest_a[1], latest_a[2],
                        latest_g[0], latest_g[1], latest_g[2]
                    ]
                    self.session_data_log.append(row_entry)
                
                has_new_data = True
            except queue.Empty:
                break 
            
        if has_new_data:
            self.lbl_hand_data.text = (
                f"FLEX SENSORS (NOW / MAX):\n"
                f"F1: {latest_f[0]:.2f}V ({self.flex_peaks[0]:.2f}V) | F2: {latest_f[1]:.2f}V ({self.flex_peaks[1]:.2f}V)\n"
                f"F3: {latest_f[2]:.2f}V ({self.flex_peaks[2]:.2f}V) | F4: {latest_f[3]:.2f}V ({self.flex_peaks[3]:.2f}V)\n"
                f"F5: {latest_f[4]:.2f}V ({self.flex_peaks[4]:.2f}V)"
            )
            
            # 🛠️ SANITIZED: Displaying direct raw integer variables without formatting symbols or 'V' tokens
            self.lbl_emg_data.text = (
                f"EMG PROFILES (NOW / MAX):\n"
                f"EMG1: {latest_emg[0]} ({self.emg_peaks[0]})\n"
                f"EMG2: {latest_emg[1]} ({self.emg_peaks[1]})\n"
                f"EMG3: {latest_emg[2]} ({self.emg_peaks[2]})"
            )
            
            self.lbl_motion_data.text = (
                f"6-AXIS IMU METRICS:\n"
                f"ACC: X:{latest_a[0]:+.2f}g | Y:{latest_a[1]:+.2f}g | Z:{latest_a[2]:+.2f}g\n"
                f"GYR: X:{latest_g[0]:+05.0f} | Y:{latest_g[1]:+05.0f} | Z:{latest_g[2]:+05.0f}"
            )

            self.redraw_grid_waveforms()

    def redraw_grid_waveforms(self):
        for i in range(14):
            widget = self.graph_areas[i]
            line = self.plot_lines[i]
            buf = self.buffers[i]
            
            self.plot_bgs[i].pos, self.plot_bgs[i].size = widget.pos, widget.size
            w_w, w_h = widget.width, widget.height
            w_x, w_y = widget.x, widget.y
            x_step = w_w / (self.points_count - 1)
            
            pts = []
            for idx, val in enumerate(buf):
                x = w_x + (idx * x_step)
                
                # Split Rendering Bounds Matrix Check
                if i < 5:     # Flex (Voltage scaled to 4.096V full limits)
                    y = w_y + (max(0.0, min(4.096, val)) / 4.096) * w_h
                elif i < 8:   # EMG (Raw counts scaled to 32767 peak limit)
                    y = w_y + (max(0.0, min(32767.0, val)) / 32767.0) * w_h
                elif i < 11:  # Accelerometer (-2.0g to +2.0g limits)
                    y = w_y + max(0.0, min(1.0, (val + 2.0) / 4.0)) * w_h
                else:         # Gyroscope (-250 dps to +250 dps limits)
                    y = w_y + max(0.0, min(1.0, (val + 250.0) / 500.0)) * w_h
                    
                pts.extend([x, y])
            line.points = pts

    def update_rect(self, instance, value): self.bg_rect.pos, self.bg_rect.size = instance.pos, instance.size
    def update_sidebar_bg(self, instance, value): self.sidebar_bg.pos, self.sidebar_bg.size = instance.pos, instance.size
    def update_panel_bg(self, instance, value): self.panel_bg.pos, self.panel_bg.size = instance.pos, instance.size

if __name__ == '__main__':
    TelemetryDashboard().run()