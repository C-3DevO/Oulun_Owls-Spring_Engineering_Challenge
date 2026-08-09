#pragma once

#include "scheduler_policy.h"
#include "srsran/adt/slotted_array.h"
#include "srsran/scheduler/config/scheduler_expert_config.h"
#include "srsran/support/math/exponential_averager.h"
#include <unordered_map>

namespace srsran {

/// Pure AI-based time-domain scheduler.
class scheduler_time_ai final : public scheduler_policy
{
public:
  scheduler_time_ai(const scheduler_ue_expert_config& expert_cfg_, du_cell_index_t cell_index);

  void add_ue(du_ue_index_t ue_index) override;
  void rem_ue(du_ue_index_t ue_index) override;

  void compute_ue_dl_priorities(slot_point              pdcch_slot,
                                slot_point              pdsch_slot,
                                span<ue_newtx_candidate> ue_candidates) override;

  void compute_ue_ul_priorities(slot_point              pdcch_slot,
                                slot_point              pusch_slot,
                                span<ue_newtx_candidate> ue_candidates) override;

  void save_dl_newtx_grants(span<const dl_msg_alloc> dl_grants) override;
  void save_ul_newtx_grants(span<const ul_sched_info> ul_grants) override;

private:
  static constexpr double forbid_prio = std::numeric_limits<double>::lowest();

  const du_cell_index_t cell_index;
  const double exp_avg_alpha = 0.01;

  struct ue_ctxt {
    ue_ctxt(du_ue_index_t ue_index_,
            du_cell_index_t cell_index_,
            const scheduler_time_ai* parent_);

    [[nodiscard]] double total_dl_avg_rate() const
    {
      return total_dl_avg_rate_.get_average_value();
    }

    [[nodiscard]] double total_ul_avg_rate() const
    {
      return total_ul_avg_rate_.get_average_value();
    }

    [[nodiscard]] double get_last_dl_bytes() const
    {
      return allocated_bytes;
    }

    void save_dl_alloc(uint32_t total_alloc_bytes);
    void save_ul_alloc(unsigned alloc_bytes);
    void update_ul_avg(unsigned nof_slots_elapsed);
    void update_dl_avg(unsigned nof_slots_elapsed);

    const du_ue_index_t       ue_index;
    const du_cell_index_t     cell_index;
    const scheduler_time_ai*  parent;
    
    slot_point prev_pdsch_slot;

    // ============================================================
    // DQN TRANSITION STORAGE
    // ============================================================

    // Previous state
    double prev_cqi            = 0.0;
    double prev_buffer         = 0.0;
    double prev_avg_rate       = 0.0;
    double prev_last_bytes     = 0.0;

    // Diagnostic state features
    double prev_estimated_rate = 0.0;
    double prev_pf_metric      = 0.0;

    // Previous DQN decision
    int    prev_action         = 0;
    double prev_scale          = 1.0;
    double prev_priority       = 0.0;

    // Previous transition reward
    double prev_reward         = 0.0;

    bool has_prev = false;

    // ============================================================
    // CURRENT SCHEDULING OUTCOME
    // ============================================================

    bool scheduled = false;

    uint32_t allocated_prbs  = 0;
    uint32_t allocated_bytes = 0;

    uint8_t mcs      = 0;
    uint8_t prev_mcs = 0;

    uint8_t harq_id = 0;
    bool    harq_retx = false;

    double reward = 0.0;

  private:
    unsigned dl_sum_alloc_bytes = 0;
    unsigned ul_sum_alloc_bytes = 0;

    exp_average_fast_start<double> total_dl_avg_rate_;
    exp_average_fast_start<double> total_ul_avg_rate_;
  };

  slotted_id_table<du_ue_index_t, ue_ctxt, MAX_NOF_DU_UES> ue_history_db;

  slot_point last_pdsch_slot;
  slot_point last_pusch_slot;
};

} // namespace srsran
