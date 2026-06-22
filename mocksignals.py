import json
import random
import time
from datetime import datetime
from pathlib import Path


class MockSignals:
    def __init__(self) -> None:
        self.elapsed_seconds = 0
        self.phase = 1
        self.state = {
            "SOC": 78.0,
            "SOH": 95.0,
            "BatteryVoltage": 395.0,
            "BatteryCurrent": 36.0,
            "BatteryTemp": 31.0,
            "CellVoltageMax": 4.21,
            "CellVoltageMin": 4.16,
            "CellVoltageDiff": 0.05,
            "CellMaxTemp": 35.0,
            "CellMinTemp": 28.5,
            "BatteryCoolingState": 0,
            "BatteryChargeCycles": 135,
            "RemainingRange": 335.0,
            "ChargingState": False,
            "FastChargeEnabled": False,
            "MotorTemp": 48.0,
            "MotorRPM": 3100,
            "MotorTorque": 120.0,
            "MotorCurrent": 90.0,
            "InverterTemp": 42.0,
            "InverterVoltage": 365.0,
            "DriveMode": "NORMAL",
            "RegenerativeBraking": 0.0,
            "PowerOutput": 30.0,
            "VehicleSpeed": 60.0,
            "Gear": "D",
            "BrakePedal": 0.0,
            "AcceleratorPedal": 18.0,
            "SteeringAngle": 2.0,
            "ParkingBrake": False,
            "DoorStatus": "CLOSED",
            "SeatbeltStatus": "FASTENED",
            "IgnitionState": "ON",
            "CoolantTemp": 34.0,
            "CoolingPumpSpeed": 20,
            "RadiatorFanSpeed": 18,
            "CabinTemp": 22.5,
            "OutsideTemp": 18.0,
            "HVACState": "AUTO",
            "DCBusVoltage": 390.0,
            "AuxBatteryVoltage": 12.4,
            "ChargerVoltage": 230.0,
            "ChargerCurrent": 0.0,
            "ChargingPortLocked": False,
            "ACConnected": False,
            "DCDCConverterTemp": 44.0,
            "IsolationFault": False,
            "OverVoltageFault": False,
            "UnderVoltageFault": False,
            "OverCurrentFault": False,
            "OverheatFault": False,
            "CommunicationFault": False,
            "BMSFault": False,
            "MotorFault": False,
            "SensorFault": False,
            "CANTimeout": False,
        }

    @staticmethod
    def clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    @staticmethod
    def noise(value: float, amount: float) -> float:
        return value + random.uniform(-amount, amount)

    def update_phase(self) -> None:
        if self.elapsed_seconds >= 70:
            self.phase = 3
        elif self.elapsed_seconds >= 50:
            self.phase = 2
        else:
            self.phase = 1

    def compute_cooling(self, temperature: float) -> int:
        if temperature > 50:
            return 100
        if temperature > 40:
            return 70
        if temperature > 35:
            return 40
        return 18

    def export_dataset(self, seconds: int = 80, output_path: str = "data/mock_signals.json") -> None:
        generator = MockSignals()
        samples = [generator.generate() for _ in range(seconds)]
        output_file = Path(output_path)
        if not output_file.is_absolute():
            output_file = Path(__file__).resolve().parent.joinpath(output_path)

        if not output_file.parent.exists():
            output_file.parent.mkdir(parents=True, exist_ok=True)

        output_file.write_text(json.dumps(samples, indent=2), encoding="utf-8")

    def generate(self) -> dict:
        self.elapsed_seconds += 1
        self.update_phase()

        base_speed = self.state["VehicleSpeed"]
        base_soc = self.state["SOC"]
        base_bat_temp = self.state["BatteryTemp"]
        base_motor_temp = self.state["MotorTemp"]
        base_inv_temp = self.state["InverterTemp"]
        base_current = self.state["BatteryCurrent"]
        cell_diff = self.state["CellVoltageDiff"]

        if self.phase == 1:
            target_speed = random.uniform(50, 80)
            self.state["VehicleSpeed"] = self.clamp(base_speed + (target_speed - base_speed) * 0.08 + random.uniform(-1.5, 1.5), 0.0, 100.0)
            self.state["BatteryCurrent"] = self.clamp(base_current + random.uniform(0.5, 2.5), -10.0, 120.0)
            self.state["SOC"] = self.clamp(base_soc - random.uniform(0.12, 0.24), 10.0, 100.0)
            self.state["BatteryTemp"] = self.clamp(base_bat_temp + random.uniform(0.08, 0.18), 20.0, 55.0)
            self.state["MotorTemp"] = self.clamp(base_motor_temp + random.uniform(0.06, 0.14), 20.0, 95.0)
            self.state["InverterTemp"] = self.clamp(base_inv_temp + random.uniform(0.04, 0.1), 20.0, 90.0)
            self.state["CellVoltageDiff"] = self.clamp(cell_diff + random.uniform(-0.002, 0.003), 0.01, 0.16)
            self.state["DriveMode"] = "NORMAL"
            self.state["AcceleratorPedal"] = self.clamp(self.noise(self.state["AcceleratorPedal"], 3.5), 10.0, 30.0)
            self.state["BrakePedal"] = self.clamp(self.noise(self.state["BrakePedal"], 1.2), 0.0, 8.0)
            self.state["RegenerativeBraking"] = 0.0
        elif self.phase == 2:
            self.state["VehicleSpeed"] = self.clamp(base_speed + random.uniform(1.5, 3.5), 60.0, 130.0)
            self.state["BatteryCurrent"] = self.clamp(base_current + random.uniform(6.0, 14.0), 30.0, 180.0)
            self.state["SOC"] = self.clamp(base_soc - random.uniform(0.28, 0.5), 8.0, 100.0)
            self.state["BatteryTemp"] = self.clamp(base_bat_temp + random.uniform(0.24, 0.42), 25.0, 70.0)
            self.state["MotorTemp"] = self.clamp(base_motor_temp + random.uniform(0.4, 0.8), 30.0, 105.0)
            self.state["InverterTemp"] = self.clamp(base_inv_temp + random.uniform(0.3, 0.7), 25.0, 98.0)
            self.state["CellVoltageDiff"] = self.clamp(cell_diff + random.uniform(0.003, 0.012), 0.01, 0.22)
            self.state["DriveMode"] = "POWER"
            self.state["AcceleratorPedal"] = self.clamp(self.noise(self.state["AcceleratorPedal"], 5.8), 45.0, 92.0)
            self.state["BrakePedal"] = self.clamp(self.noise(self.state["BrakePedal"], 1.8), 0.0, 14.0)
            self.state["RegenerativeBraking"] = 0.0
        else:
            self.state["VehicleSpeed"] = self.clamp(base_speed + random.uniform(-0.5, 2.3), 55.0, 140.0)
            self.state["BatteryCurrent"] = self.clamp(base_current + random.uniform(8.0, 20.0), 60.0, 240.0)
            self.state["SOC"] = self.clamp(base_soc - random.uniform(0.6, 1.0), 5.0, 80.0)
            self.state["BatteryTemp"] = self.clamp(base_bat_temp + random.uniform(0.55, 1.1), 35.0, 82.0)
            self.state["MotorTemp"] = self.clamp(base_motor_temp + random.uniform(0.9, 1.3), 40.0, 120.0)
            self.state["InverterTemp"] = self.clamp(base_inv_temp + random.uniform(0.6, 1.1), 40.0, 108.0)
            self.state["CellVoltageDiff"] = self.clamp(cell_diff + random.uniform(0.01, 0.03), 0.01, 0.42)
            self.state["DriveMode"] = "POWER"
            self.state["AcceleratorPedal"] = self.clamp(self.noise(self.state["AcceleratorPedal"], 6.2), 55.0, 100.0)
            self.state["BrakePedal"] = self.clamp(self.noise(self.state["BrakePedal"], 5.2), 0.0, 22.0)
            self.state["RegenerativeBraking"] = self.clamp(random.choice([0.0, 0.0, 18.0, 22.0]), 0.0, 24.0)

        self.state["BatteryPower"] = round(self.state["BatteryVoltage"] * self.state["BatteryCurrent"] / 1000.0, 1)
        self.state["PowerOutput"] = round(self.state["VehicleSpeed"] * 0.35 + random.uniform(-3.0, 3.0), 1)
        self.state["MotorCurrent"] = self.clamp(self.state["BatteryCurrent"] * 0.95 + random.uniform(-5.0, 5.0), 10.0, 280.0)
        self.state["InverterVoltage"] = self.clamp(self.state["InverterVoltage"] + random.uniform(-1.5, 1.5), 330.0, 455.0)
        self.state["InverterCurrent"] = self.clamp(self.state["MotorCurrent"] * 0.85 + random.uniform(-4.0, 4.0), 10.0, 260.0)
        self.state["BatteryVoltage"] = self.clamp(self.state["BatteryVoltage"] + random.uniform(-0.6, 0.6), 285.0, 430.0)
        self.state["SOC"] = self.clamp(self.state["SOC"], 3.0, 100.0)
        self.state["BatteryTemp"] = self.clamp(self.state["BatteryTemp"], 21.0, 85.0)
        self.state["MotorTemp"] = self.clamp(self.state["MotorTemp"], 24.0, 130.0)
        self.state["InverterTemp"] = self.clamp(self.state["InverterTemp"], 24.0, 115.0)
        self.state["CellVoltageMax"] = self.clamp(4.10 + self.state["CellVoltageDiff"] * 0.4 + random.uniform(-0.02, 0.02), 3.98, 4.35)
        self.state["CellVoltageMin"] = self.clamp(self.state["CellVoltageMax"] - self.state["CellVoltageDiff"], 3.70, self.state["CellVoltageMax"])
        self.state["CellMaxTemp"] = self.clamp(self.state["BatteryTemp"] + random.uniform(3.0, 7.0), 25.0, 90.0)
        self.state["CellMinTemp"] = self.clamp(self.state["BatteryTemp"] - random.uniform(2.0, 5.0), 18.0, self.state["CellMaxTemp"])
        self.state["BatteryCoolingState"] = 1 if self.state["BatteryTemp"] > 40 else 0
        self.state["BatteryChargeCycles"] = int(self.state["BatteryChargeCycles"] + (1 if self.elapsed_seconds % 60 == 0 else 0))
        self.state["RemainingRange"] = self.clamp(self.state["SOC"] * 4.2 + random.uniform(-5.0, 5.0), 12.0, 430.0)
        self.state["ChargerCurrent"] = 0.0
        self.state["CoolingPumpSpeed"] = self.compute_cooling(self.state["BatteryTemp"])
        self.state["RadiatorFanSpeed"] = self.state["CoolingPumpSpeed"]
        self.state["CabinTemp"] = self.clamp(self.state["CabinTemp"] + random.uniform(-0.1, 0.2), 18.0, 28.0)
        self.state["OutsideTemp"] = self.clamp(self.state["OutsideTemp"] + random.uniform(-0.15, 0.15), -10.0, 45.0)
        self.state["HVACState"] = "AUTO"
        self.state["DCBusVoltage"] = self.clamp(380.0 + (self.state["BatteryVoltage"] - 320.0) * 1.3 + random.uniform(-4.0, 4.0), 330.0, 430.0)
        self.state["AuxBatteryVoltage"] = self.clamp(12.3 + random.uniform(-0.2, 0.2), 11.8, 14.0)
        self.state["DCDCConverterTemp"] = self.clamp(self.state["InverterTemp"] * 0.32 + random.uniform(-2.0, 2.0), 30.0, 98.0)
        self.state["ChargingState"] = False
        self.state["FastChargeEnabled"] = False
        self.state["ChargingPortLocked"] = False
        self.state["ACConnected"] = False

        self.state["OverheatFault"] = self.state["BatteryTemp"] > 65 or self.state["MotorTemp"] > 100 or self.state["InverterTemp"] > 95
        self.state["UnderVoltageFault"] = self.state["BatteryVoltage"] < 300
        self.state["OverCurrentFault"] = self.state["BatteryCurrent"] > 200
        self.state["OverVoltageFault"] = self.state["BatteryVoltage"] > 425
        self.state["IsolationFault"] = False
        self.state["CommunicationFault"] = self.phase == 3 and random.random() < 0.08
        self.state["BMSFault"] = self.state["OverheatFault"] or self.state["UnderVoltageFault"] or self.state["CellVoltageDiff"] > 0.25
        self.state["MotorFault"] = self.state["MotorTemp"] > 105 or self.state["BatteryCurrent"] > 220
        self.state["SensorFault"] = self.phase == 3 and random.random() < 0.06
        self.state["CANTimeout"] = self.phase == 3 and random.random() < 0.05

        self.state["SteeringAngle"] = self.clamp(self.noise(self.state["SteeringAngle"], 2.2), -30.0, 30.0)
        self.state["Gear"] = "D" if self.state["VehicleSpeed"] > 0.5 else "P"
        self.state["ParkingBrake"] = False

        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "SOC": round(self.state["SOC"], 1),
            "SOH": round(self.state["SOH"], 1),
            "BatteryVoltage": round(self.state["BatteryVoltage"], 1),
            "BatteryCurrent": round(self.state["BatteryCurrent"], 1),
            "BatteryPower": round(self.state["BatteryPower"], 1),
            "BatteryTemp": round(self.state["BatteryTemp"], 1),
            "CellVoltageMax": round(self.state["CellVoltageMax"], 3),
            "CellVoltageMin": round(self.state["CellVoltageMin"], 3),
            "CellVoltageDiff": round(self.state["CellVoltageDiff"], 3),
            "CellMaxTemp": round(self.state["CellMaxTemp"], 1),
            "CellMinTemp": round(self.state["CellMinTemp"], 1),
            "BatteryCoolingState": self.state["BatteryCoolingState"],
            "BatteryChargeCycles": self.state["BatteryChargeCycles"],
            "RemainingRange": round(self.state["RemainingRange"], 1),
            "ChargingState": self.state["ChargingState"],
            "FastChargeEnabled": self.state["FastChargeEnabled"],
            "MotorTemp": round(self.state["MotorTemp"], 1),
            "MotorRPM": int(self.state["MotorRPM"]),
            "MotorTorque": round(self.state["MotorTorque"], 1),
            "MotorCurrent": round(self.state["MotorCurrent"], 1),
            "InverterTemp": round(self.state["InverterTemp"], 1),
            "InverterVoltage": round(self.state["InverterVoltage"], 1),
            "DriveMode": self.state["DriveMode"],
            "RegenerativeBraking": round(self.state["RegenerativeBraking"], 1),
            "PowerOutput": round(self.state["PowerOutput"], 1),
            "VehicleSpeed": round(self.state["VehicleSpeed"], 1),
            "Gear": self.state["Gear"],
            "BrakePedal": round(self.state["BrakePedal"], 1),
            "AcceleratorPedal": round(self.state["AcceleratorPedal"], 1),
            "SteeringAngle": round(self.state["SteeringAngle"], 1),
            "ParkingBrake": self.state["ParkingBrake"],
            "DoorStatus": self.state["DoorStatus"],
            "SeatbeltStatus": self.state["SeatbeltStatus"],
            "IgnitionState": self.state["IgnitionState"],
            "CoolantTemp": round(self.state["CoolantTemp"], 1),
            "CoolingPumpSpeed": self.state["CoolingPumpSpeed"],
            "RadiatorFanSpeed": self.state["RadiatorFanSpeed"],
            "CabinTemp": round(self.state["CabinTemp"], 1),
            "OutsideTemp": round(self.state["OutsideTemp"], 1),
            "HVACState": self.state["HVACState"],
            "DCBusVoltage": round(self.state["DCBusVoltage"], 1),
            "AuxBatteryVoltage": round(self.state["AuxBatteryVoltage"], 2),
            "ChargerVoltage": round(self.state["ChargerVoltage"], 1),
            "ChargerCurrent": round(self.state["ChargerCurrent"], 1),
            "ChargingPortLocked": self.state["ChargingPortLocked"],
            "ACConnected": self.state["ACConnected"],
            "DCDCConverterTemp": round(self.state["DCDCConverterTemp"], 1),
            "IsolationFault": self.state["IsolationFault"],
            "OverVoltageFault": self.state["OverVoltageFault"],
            "UnderVoltageFault": self.state["UnderVoltageFault"],
            "OverCurrentFault": self.state["OverCurrentFault"],
            "OverheatFault": self.state["OverheatFault"],
            "CommunicationFault": self.state["CommunicationFault"],
            "BMSFault": self.state["BMSFault"],
            "MotorFault": self.state["MotorFault"],
            "SensorFault": self.state["SensorFault"],
            "CANTimeout": self.state["CANTimeout"],
        }


def generate() -> dict:
    generator = MockSignals()
    return generator.generate()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate or export mock vehicle signal streams.")
    parser.add_argument("--export", "-e", action="store_true", help="Export a dataset to JSON instead of streaming to stdout.")
    parser.add_argument("--seconds", "-s", type=int, default=80, help="Number of seconds of mock data to export.")
    parser.add_argument("--output", "-o", default="data/mock_signals.json", help="Output file path for exported dataset.")
    args = parser.parse_args()

    generator = MockSignals()
    if args.export:
        generator.export_dataset(seconds=args.seconds, output_path=args.output)
        print(f"Exported {args.seconds} samples to {args.output}")
    else:
        while True:
            print(generator.generate())
            time.sleep(1)
        time.sleep(1)
