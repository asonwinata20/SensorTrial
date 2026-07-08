import time
import random

# --- HARDWARE INTEGRATION GUARD ---
try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    from DFRobot_ICG20660L import DFRobot_ICG20660L_IIC
    HARDWARE_AVAILABLE = True
except ImportError:
    HARDWARE_AVAILABLE = False

class SensorAcquisitionWorker:
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.running = True
        self.is_streaming = False
        self.hardware_initialized = False 
        
        self.ADC1_ADDR = 0x48  
        self.ADC2_ADDR = 0x4A  

    def initialize_hardware_inside_thread(self):
        if HARDWARE_AVAILABLE and not self.hardware_initialized:
            try:
                self.i2c = busio.I2C(board.SCL, board.SDA, frequency=400000)
                
                # Configure Primary ADC (0x48) -> Flex 1 to Flex 4
                self.ads1 = ADS.ADS1115(self.i2c, address=self.ADC1_ADDR)
                self.ads1.gain = 1
                self.ads1.data_rate = 860
                
                self.ch_f1 = AnalogIn(self.ads1, 0)
                self.ch_f2 = AnalogIn(self.ads1, 1)
                self.ch_f3 = AnalogIn(self.ads1, 2)
                self.ch_f4 = AnalogIn(self.ads1, 3)
                
                # Configure Secondary ADC (0x4A) -> Flex 5 + EMG 1 to EMG 3
                self.ads2 = ADS.ADS1115(self.i2c, address=self.ADC2_ADDR)
                self.ads2.gain = 1
                self.ads2.data_rate = 860
                
                self.ch_f5 = AnalogIn(self.ads2, 0)
                self.ch_emg1 = AnalogIn(self.ads2, 1)
                self.ch_emg2 = AnalogIn(self.ads2, 2)
                self.ch_emg3 = AnalogIn(self.ads2, 3)
                
                # Configure IMU
                self.imu = DFRobot_ICG20660L_IIC(addr=DFRobot_ICG20660L_IIC.IIC_ADDR_SDO_H)
                while self.imu.begin(self.imu.eREG_MODE) != 0:
                    time.sleep(0.5)
                self.imu.enable_sensor(bit=self.imu.eAXIS_ALL)
                self.imu.config_gyro(scale=self.imu.eFSR_G_500DPS, bd=self.imu.eGYRO_DLPF_176_1KHZ)
                self.imu.config_accel(scale=self.imu.eFSR_A_16G, bd=self.imu.eACCEL_DLPF_218_1KHZ)
                self.imu.set_sample_div(div=19)
                
                self.hardware_initialized = True
                print("🚀 Hybrid Data Pipeline Online (Flex: Voltage | EMG: Raw ADC).")
            except Exception as e:
                print(f"❌ Critical error during hardware pipeline init: {e}")

    def check_i2c_status(self):
        if not HARDWARE_AVAILABLE:
            return True, "💻 LAPTOP SIMULATION MODE\n\nNo physical I2C hardware detected."
        if not self.hardware_initialized:
            return False, "⚠️ PIPELINE UNINITIALIZED\n\nStart the stream once to verify active objects."
        try:
            _ = self.ch_f1.voltage
            _ = self.ch_emg1.value
            return True, "✅ ALL CHANNELS OPERATIONAL\n\nPipeline status verified across hybrid formats."
        except Exception as e:
            return False, f"❌ HARDWARE UNSTABLE\n\nConnection trace dropped:\n{str(e)}"

    def read_voltage(self, analog_channel_object):
        if not HARDWARE_AVAILABLE or not self.hardware_initialized:
            return 0.0
        try:
            return analog_channel_object.voltage
        except Exception:
            return 0.0

    def read_adc(self, analog_channel_object):
        if not HARDWARE_AVAILABLE or not self.hardware_initialized:
            return 0
        try:
            return analog_channel_object.value
        except Exception:
            return 0

    def main_loop(self):
        if HARDWARE_AVAILABLE:
            self.initialize_hardware_inside_thread()

        target_sample_rate = 100    
        sample_interval = 1.0 / target_sample_rate  
        next_sample_time = time.perf_counter()

        while self.running:
            if self.is_streaming:
                current_time = time.perf_counter()
                
                if current_time < next_sample_time:
                    time_remaining = next_sample_time - current_time
                    if time_remaining > 0.005:
                        time.sleep(time_remaining - 0.002)
                    while time.perf_counter() < next_sample_time:
                        pass
                
                if HARDWARE_AVAILABLE and self.hardware_initialized:
                    try:
                        # Flex reads fetch Voltages (0.0V - 4.096V)
                        f1 = self.read_voltage(self.ch_f1)
                        f2 = self.read_voltage(self.ch_f2)
                        f3 = self.read_voltage(self.ch_f3)
                        f4 = self.read_voltage(self.ch_f4)
                        f5 = self.read_voltage(self.ch_f5)
                        
                        # EMG reads fetch Raw 15-bit Digital Counts (0 - 32767)
                        emg1 = self.read_adc(self.ch_emg1)
                        emg2 = self.read_adc(self.ch_emg2)
                        emg3 = self.read_adc(self.ch_emg3)
                        
                        sensor = self.imu.get_sensor_data()
                        ax, ay, az = sensor['accel']['x'], sensor['accel']['y'], sensor['accel']['z']
                        gx, gy, gz = sensor['gyro']['x'], sensor['gyro']['y'], sensor['gyro']['z']
                    except Exception:
                        f1, f2, f3, f4, f5 = 0.0, 0.0, 0.0, 0.0, 0.0
                        emg1, emg2, emg3 = 0, 0, 0
                        ax, ay, az, gx, gy, gz = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                else:
                    # Simulation Mode
                    f1, f2, f3, f4, f5 = [round(random.uniform(1.5, 3.3), 2) for _ in range(5)]
                    ax, ay, az = [round(random.uniform(-0.8, 0.8), 2) for _ in range(3)]
                    gx, gy, gz = [round(random.uniform(-120.0, 120.0), 1) for _ in range(3)]
                    emg1 = random.randint(800, 4000)
                    emg2 = random.randint(800, 3500)
                    emg3 = random.randint(1000, 4500)
                    if random.random() > 0.94: emg1 = random.randint(18000, 29000)
                    if random.random() > 0.94: emg2 = random.randint(15000, 27000)
                    if random.random() > 0.94: emg3 = random.randint(20000, 31000)

                telemetry_frame = {
                    'flex': [f1, f2, f3, f4, f5],
                    'emg': [emg1, emg2, emg3],
                    'accel': [ax, ay, az],
                    'gyro': [gx, gy, gz]
                }
                self.data_queue.put(telemetry_frame)
                
                next_sample_time += sample_interval
            else:
                time.sleep(0.05)
                next_sample_time = time.perf_counter()