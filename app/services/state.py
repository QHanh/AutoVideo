import ast
from abc import ABC, abstractmethod

from app.config import config
from app.models import const # Đảm bảo import const


# Lớp cơ sở cho quản lý trạng thái
class BaseState(ABC):
    @abstractmethod
    def update_task(self, task_id: str, state: int, progress: int = 0, **kwargs):
        pass

    @abstractmethod
    def get_task(self, task_id: str):
        pass

    @abstractmethod
    def get_all_tasks(self, page: int, page_size: int):
        pass
    
    @abstractmethod
    def delete_task(self, task_id: str):
        pass


# Quản lý trạng thái trong bộ nhớ
class MemoryState(BaseState):
    def __init__(self):
        self._tasks = {} # Từ điển để lưu trữ các tác vụ

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        end = start + page_size
        tasks = list(self._tasks.values())
        total = len(tasks)
        return tasks[start:end], total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        self._tasks[task_id] = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            **kwargs,
        }

    def get_task(self, task_id: str):
        return self._tasks.get(task_id, None)

    def delete_task(self, task_id: str):
        if task_id in self._tasks:
            del self._tasks[task_id]


# Quản lý trạng thái Redis
class RedisState(BaseState):
    def __init__(self, host="localhost", port=6379, db=0, password=None):
        import redis # Import redis ở đây để tránh lỗi nếu redis không được cài đặt và không dùng

        self._redis = redis.StrictRedis(host=host, port=port, db=db, password=password)

    def get_all_tasks(self, page: int, page_size: int):
        start = (page - 1) * page_size
        # end = start + page_size # Không dùng trực tiếp end ở đây vì scan không đảm bảo thứ tự
        tasks = []
        cursor = 0
        total_keys_scanned = 0 # Tổng số keys đã scan được (không phải tổng số keys trong DB)
        retrieved_count = 0 # Số lượng tasks đã retrieve cho trang hiện tại

        # Lặp cho đến khi duyệt hết database hoặc lấy đủ số lượng tasks cho trang hiện tại
        while True:
            # Lấy một lô khóa từ Redis
            # Count ở đây chỉ là gợi ý, không đảm bảo số lượng khóa trả về chính xác
            cursor, keys_bytes = self._redis.scan(cursor, match='*', count=page_size * 2) 
            
            # Decode các khóa từ bytes sang utf-8
            keys = [k.decode('utf-8') for k in keys_bytes]

            total_keys_scanned += len(keys)

            # Lọc và lấy tasks cho trang hiện tại
            # Logic này phức tạp hơn để đảm bảo lấy đúng tasks cho trang đó
            for key in keys:
                if retrieved_count >= page_size:
                    break # Đã lấy đủ cho trang hiện tại

                # Kiểm tra xem task này có nằm trong phạm vi của trang hiện tại không
                # Đây là một giải pháp đơn giản, không lý tưởng cho phân trang thực sự trên tập lớn
                # vì SCAN không có thứ tự. Một giải pháp tốt hơn là sử dụng SORTED SETs.
                if start <= len(tasks) + retrieved_count < start + page_size:
                    task_data = self._redis.hgetall(key)
                    task = {
                        k.decode("utf-8"): self._convert_to_original_type(v) for k, v in task_data.items()
                    }
                    tasks.append(task)
                    retrieved_count += 1
                
            if cursor == 0: # Đã scan hết database
                break
            if retrieved_count >= page_size: # Đã lấy đủ tasks cho trang hiện tại
                break

        # Để có tổng số chính xác của tất cả các tasks trong Redis, cần một cách khác
        # hoặc chấp nhận tổng số chỉ là số keys đã scan được cho đến khi đủ page_size
        # hoặc scan toàn bộ để lấy tổng số thực tế (có thể chậm).
        # Ở đây, tôi sẽ ước tính tổng số dựa trên số keys đã scan được cho đến khi đủ dữ liệu cho trang.
        # Đối với một hệ thống quản lý tác vụ đơn giản, điều này có thể chấp nhận được.
        # Nếu cần tổng số chính xác, cần xem xét lại cách lưu trữ tasks trong Redis (ví dụ: dùng set các task_id)
        
        # Tuy nhiên, để khớp với hành vi của MemoryState (trả về tổng số tasks hiện có)
        # chúng ta cần lấy tất cả các keys và đếm chúng.
        # Cách tối ưu hơn cho Redis để có tổng số là duy trì một counter hoặc một set các task_id.
        # Trong ví dụ này, để giữ đơn giản và tương tự bản gốc:
        all_keys = self._redis.keys('*')
        total_tasks_in_db = len(all_keys)

        # Trả về các tasks đã lấy được và tổng số tasks trong DB
        return tasks, total_tasks_in_db

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        fields = {
            "task_id": task_id,
            "state": state,
            "progress": progress,
            **kwargs,
        }

        for field, value in fields.items():
            # Redis HSET chỉ chấp nhận bytes, strings, ints, floats
            # Các kiểu phức tạp hơn như list, dict cần được tuần tự hóa (ví dụ: JSON)
            # Trong bản gốc, dường như chúng được lưu dưới dạng str() và được ast.literal_eval() khi đọc
            self._redis.hset(task_id, field, str(value))

    def get_task(self, task_id: str):
        task_data = self._redis.hgetall(task_id)
        if not task_data:
            return None

        task = {
            key.decode("utf-8"): self._convert_to_original_type(value)
            for key, value in task_data.items()
        }
        return task

    def delete_task(self, task_id: str):
        self._redis.delete(task_id)

    @staticmethod
    def _convert_to_original_type(value):
        """
        Chuyển đổi giá trị từ chuỗi byte sang kiểu dữ liệu gốc của nó.
        Có thể mở rộng phương thức này để xử lý các kiểu dữ liệu khác khi cần.
        """
        value_str = value.decode("utf-8")

        try:
            # Cố gắng chuyển đổi chuỗi byte thành list/dict nếu có thể
            return ast.literal_eval(value_str)
        except (ValueError, SyntaxError):
            pass

        if value_str.isdigit():
            return int(value_str)
        # Nếu là boolean (True/False) được lưu dưới dạng chuỗi
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False
        
        # Thêm các chuyển đổi khác ở đây nếu cần (ví dụ: float)
        try:
            return float(value_str)
        except ValueError:
            pass

        return value_str


# Trạng thái toàn cục
_enable_redis = config.app.get("enable_redis", False)
_redis_host = config.app.get("redis_host", "localhost")
_redis_port = config.app.get("redis_port", 6379)
_redis_db = config.app.get("redis_db", 0)
_redis_password = config.app.get("redis_password", None)

# Khởi tạo đối tượng state tùy thuộc vào cấu hình Redis
state = (
    RedisState(
        host=_redis_host, port=_redis_port, db=_redis_db, password=_redis_password
    )
    if _enable_redis
    else MemoryState()
)


if __name__ == "__main__":
    # Ví dụ sử dụng MemoryState (mặc định nếu Redis không bật)
    print("--- Thử nghiệm MemoryState ---")
    memory_state_manager = MemoryState()
    
    # Tạo và cập nhật tác vụ
    memory_state_manager.update_task("task_mem_1", state=const.TASK_STATE_PROCESSING, progress=25, message="Đang xử lý mem 1")
    memory_state_manager.update_task("task_mem_2", state=const.TASK_STATE_PROCESSING, progress=50, data={"step": "tải xuống"})
    memory_state_manager.update_task("task_mem_1", state=const.TASK_STATE_COMPLETE, progress=100, result="thành công")

    # Lấy tác vụ
    task1 = memory_state_manager.get_task("task_mem_1")
    print(f"Tác vụ mem_1: {task1}")

    # Lấy tất cả tác vụ (phân trang)
    all_tasks_mem, total_mem = memory_state_manager.get_all_tasks(page=1, page_size=10)
    print(f"Tất cả tác vụ mem (Tổng: {total_mem}): {all_tasks_mem}")

    # Xóa tác vụ
    memory_state_manager.delete_task("task_mem_2")
    task2_deleted = memory_state_manager.get_task("task_mem_2")
    print(f"Tác vụ mem_2 sau khi xóa: {task2_deleted}")

    # Ví dụ sử dụng RedisState (chỉ chạy nếu 'enable_redis = true' trong config.toml và Redis đang chạy)
    print("--- Thử nghiệm RedisState ---")
    # Để bật RedisState cho ví dụ này, bạn cần cấu hình config.toml:
    # [app]
    # enable_redis = true
    # redis_host = "localhost"
    # redis_port = 6379
    # redis_db = 0
    # redis_password = "your_redis_password" # Nếu có

    # Đảm bảo Redis đang chạy trước khi chạy phần này của code
    try:
        redis_state_manager = RedisState(
            host=config.app.get("redis_host"),
            port=config.app.get("redis_port"),
            db=config.app.get("redis_db"),
            password=config.app.get("redis_password"),
        )
        redis_state_manager.update_task("task_redis_1", state=const.TASK_STATE_PROCESSING, progress=10, message="Đang xử lý redis 1")
        redis_state_manager.update_task("task_redis_2", state=const.TASK_STATE_COMPLETE, progress=100, result="redis xong")

        task_redis_1 = redis_state_manager.get_task("task_redis_1")
        print(f"Tác vụ redis_1: {task_redis_1}")

        all_tasks_redis, total_redis = redis_state_manager.get_all_tasks(page=1, page_size=10)
        print(f"Tất cả tác vụ redis (Tổng: {total_redis}): {all_tasks_redis}")

        redis_state_manager.delete_task("task_redis_2")
        task_redis_2_deleted = redis_state_manager.get_task("task_redis_2")
        print(f"Tác vụ redis_2 sau khi xóa: {task_redis_2_deleted}")

    except Exception as e:
        print(f"Lỗi khi thử nghiệm RedisState (đảm bảo Redis đang chạy và config.toml đã đúng): {e}")

    pass
