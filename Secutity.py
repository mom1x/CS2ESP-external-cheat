import ctypes
import os
import sys
import random
import time
import math

PROCESS_VM_READ = 0x0010

class SafeMemoryAccessor:
    """
    Контекстный менеджер с адаптивным открытием дескриптора.
    Минимизирует время удержания хендла процесса.
    """
    def __init__(self, pid):
        self.pid = pid
        self.handle = None
        self.kernel32 = ctypes.windll.kernel32

    def __enter__(self):
        # Запрашиваем строго минимальные права
        self.handle = self.kernel32.OpenProcess(PROCESS_VM_READ, False, self.pid)
        return self.handle

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle:
            self.kernel32.CloseHandle(self.handle)

def apply_advanced_jitter():
    """
    Математическая рандомизация задержек (Шум по кривой Гаусса).
    Уничтожает циклический паттерн опроса памяти, который фиксируется
    эвристическими модулями защиты.
    """
    base_delay = 0.001
    # Создаем флуктуацию вокруг базового значения
    jitter = random.gauss(0.0005, 0.0002)
    final_delay = max(0.0005, base_delay + jitter)
    time.sleep(final_delay)

def generate_junk_code():
    """
    Полиморфный генератор "мусорных" инструкций.
    Каждый раз при вызове выполняет случайные математические операции.
    При компиляции и работе это изменяет структуру выполнения в памяти,
    затрудняя сигнатурный анализ.
    """
    iterations = random.randint(5, 15)
    holder = 0
    for i in range(iterations):
        holder += random.randint(1, 100)
        holder = (holder * random.randint(2, 5)) % 10000
    return holder

def simple_decrypt_string(encoded_bytes, key):
    """ Дешифрование строк "на лету" для скрытия API-функций из статического анализа """
    return "".join(chr(b ^ key) for b in encoded_bytes)

def check_security_environment():
    """ Проверка базовых отладчиков перед стартом """
    if ctypes.windll.kernel32.IsDebuggerPresent():
        sys.exit(0)
