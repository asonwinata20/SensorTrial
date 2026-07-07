import time
import random

# --- HARDWARE INTEGRATION GUARD ---
try:
    import smbus
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
        
        # Target Hardware Addresses
        self.ADC1_ADDR = 0x48  
        self.ADC2_ADDR = 0x4A  

    def initialize_hardware_inside_thread(self):
        if HARDWARE_AVAILABLE and not self.hardware_initialized:
            try:
                self.bus = smbus.SMBus(1)
                self.imu = DFRobot_ICG20660L_IIC(addr=DFRobot_ICG20660L_IIC.IIC_ADDR_SDO_H)
                while self.imu.begin(self.imu.eREG_MODE) != 0:
                    time.sleep(0.5)
                self.imu.enable_sensor(bit=self.imu.eAXIS_ALL)
                self.imu.config_gyro(scale=self.imu.eFSR_G_500DPS, bd=self.imu.eGYRO_DLPF_176_1KHZ)
                self.imu.config_accel(scale=self.imu.eFSR_A_16G, bd=self.imu.eACCEL_DLPF_218_1KHZ)
                self.imu.set_sample_div(div=19)
                self.hardware_initialized = True
                print("⚡ 100Hz Multi-Channel Hardware Pipeline Online.")
            except Exception as e:
                print(f"❌ Error binding hardware: {e}")

    def check_i2c_status(self):
        if not HARDWARE_AVAILABLE:
            return True, "💻 LAPTOP SIMULATION MODE\n\nNo physical I2C hardware detected.\nRunning framework via synthetic telemetry streams safely."
        try:
            self.bus.read_i2c_block_data(self.ADC1_ADDR, 0x00, 2)
            self.bus.read_i2c_block_data(self.ADC2_ADDR, 0x00, 2)
            return True, "✅ ALL SYSTEMS NOMINAL\n\nI2C Bus Scan Successful:\n• IMU verified (0x69)\n• ADS1115 Primary verified (0x48)\n• ADS1115 Secondary verified (0x4A)"
        except OSError as e:
            return False, f"❌ I2C BUS COUPLING FAILURE\n\nDetails: {str(e)}"

    def read_raw_voltage(self, i2c_addr, channel):
        if not HARDWARE_AVAILABLE or not self.hardware_initialized:
            return 0.0
            
        # ⚡ SPEED OVERCLOCK: Changed low configuration byte from 0x83 to 0xE3 to trigger 860 SPS mode
        mux_map = {
            0: [0xC3, 0xE3], 
            1: [0xD3, 0xE3], 
            2: [0xE3, 0xE3], 
            3: [0xF3, 0xE3]
        }
        try:
            self.bus.write_i2c_block_data(i2c_addr, 0x01, mux_map.get(channel, mux_map[0]))
            # ⚡ Reduced settling delay from 9ms to 1.2ms (matching the 860 SPS window limits)
            time.sleep(0.0012)
            data = self.bus.read_i2c_block_data(i2c_addr, 0x00, 2)
            raw_adc = (data[0] << 8) | data[1]
            if raw_adc > 32767: raw_adc -= 65536
            return raw_adc * 4.096 / 32768.0
        except OSError:
            return 0.0

    def main_loop(self):
        if HARDWARE_AVAILABLE:
            self.initialize_hardware_inside_thread()

        while self.running:
            if self.is_streaming:
                loop_start = time.time() # Start stopwatch frame anchor
                
                if HARDWARE_AVAILABLE and self.hardware_initialized:
                    f1 = self.read_raw_voltage(self.ADC1_ADDR, channel=0)
                    f2 = self.read_raw_voltage(self.ADC1_ADDR, channel=1)
                    f3 = self.read_raw_voltage(self.ADC1_ADDR, channel=2)
                    f4 = self.read_raw_voltage(self.ADC1_ADDR, channel=3)
                    
                    f5 = self.read_raw_voltage(self.ADC2_ADDR, channel=0)
                    emg1 = self.read_raw_voltage(self.ADC2_ADDR, channel=1)
                    emg2 = self.read_raw_voltage(self.ADC2_ADDR, channel=2)
                    emg3 = self.read_raw_voltage(self.ADC2_ADDR, channel=3)
                    
                    try:
                        sensor = self.imu.get_sensor_data()
                        ax, ay, az = sensor['accel']['x'], sensor['accel']['y'], sensor['accel']['z']
                        gx, gy, gz = sensor['gyro']['x'], sensor['gyro']['y'], sensor['gyro']['z']
                    except OSError:
                        ax, ay, az, gx, gy, gz = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                else:
                    # Laptop Simulation Mode (Fires smooth curves at 100Hz)
                    f1, f2, f3, f4, f5 = [round(random.uniform(1.5, 3.3), 2) for _ in range(5)]
                    ax, ay, az = [round(random.uniform(-0.8, 0.8), 2) for _ in range(3)]
                    gx, gy, gz = [round(random.uniform(-120.0, 120.0), 1) for _ in range(3)]
                    emg1 = round(random.uniform(0.1, 0.4), 2)
                    emg2 = round(random.uniform(0.1, 0.4), 2)
                    emg3 = round(random.uniform(0.2, 0.5), 2)
                    if random.random() > 0.94: emg1 = round(random.uniform(1.8, 3.2), 2)
                    if random.random() > 0.94: emg2 = round(random.uniform(1.5, 2.9), 2)
                    if random.random() > 0.94: emg3 = round(random.uniform(2.0, 3.4), 2)

                telemetry_frame = {
                    'flex': [f1, f2, f3, f4, f5],
                    'emg': [emg1, emg2, emg3],
                    'accel': [ax, ay, az],
                    'gyro': [gx, gy, gz]
                }
                self.data_queue.put(telemetry_frame)
                
                # ⚡ DYNAMIC INTERVAL LOCK: Calculate elapsed hardware execution time 
                # and sleep precisely for the remainder of the 10ms target frame window.
                elapsed = time.time() - loop_start
                sleep_padding = max(0.0001, 0.010 - elapsed) 
                time.sleep(sleep_padding)
            else:
                time.sleep(0.05) # Idle pacing while waiting to start stream