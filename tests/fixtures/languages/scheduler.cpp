// scheduler.cpp -- priority task scheduler used by the worker pool.

#include <algorithm>
#include <string>
#include <vector>

#define LOG_SCOPE(name) TraceScope _scope_##name(#name)

using TaskFn = void (*)(void *);

namespace worker {

class Scheduler {
public:
    explicit Scheduler(std::size_t slots)
        : slots_(slots), running_(false) {}

    ~Scheduler() {
        while (!queue_.empty()) {
            queue_.pop_back();
        }
    }

    bool submit(TaskFn fn, void *ctx);
    std::string describe() const;

    std::size_t pending() const { return queue_.size(); }

private:
    std::size_t slots_;
    bool running_;
    std::vector<std::pair<TaskFn, void *>> queue_;
};

bool Scheduler::submit(TaskFn fn, void *ctx)
{
    if (fn == nullptr) {
        return false;
    }
    if (queue_.size() >= slots_) {
        return false;
    }
    queue_.emplace_back(fn, ctx);
    return true;
}

std::string Scheduler::describe() const
{
    return "Scheduler { slots } -- submit() is a member function, not a free function";
}

template <typename T>
T clamp_to(const T &value, const T &lo, const T &hi)
{
    return std::max(lo, std::min(value, hi));
}

// void Scheduler::drain() { queue_.clear(); }

}  // namespace worker
