#include "scheduler_time_ai.h"
#include "../support/csi_report_helpers.h"
#include "../ue_scheduling/grant_params_selector.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <string>

#include "dqn_weights.h"

using namespace srsran;


// ============================================================================
// Activation
// ============================================================================

inline float relu(float x)
{
    return x > 0.0f ? x : 0.0f;
}


// ============================================================================
// PriorityNet inference
// ============================================================================

float dqn_inference(const std::array<float,5>& x)
{
    float h1[128];

    for (int i = 0; i < 128; i++) {
        float s = B0[i];

        for (int j = 0; j < 5; j++)
            s += W0[i][j] * x[j];

        h1[i] = relu(s);
    }

    float h2[128];

    for (int i = 0; i < 128; i++) {
        float s = B1[i];

        for (int j = 0; j < 128; j++)
            s += W1[i][j] * h1[j];

        h2[i] = relu(s);
    }

    float score = B2[0];

    for (int j = 0; j < 128; j++)
        score += W2[0][j] * h2[j];

    return score;
}


// ============================================================================
// RL logging
// ============================================================================

static std::string log_path =
    std::string(getenv("HOME")) + "/Oulun_Owls-Spring_Engineering_Challenge/logs/DQN_scheduler_log.csv";

static std::ofstream rl_log_file(log_path, std::ios::app);

static bool header_written = false;

// ============================================================================
// Constructor
// ============================================================================

scheduler_time_ai::scheduler_time_ai(
    const scheduler_ue_expert_config&,
    du_cell_index_t cell_index_) :
  cell_index(cell_index_)
{
}

// ============================================================================
// UE management
// ============================================================================

void scheduler_time_ai::add_ue(du_ue_index_t ue_index)
{
  ue_history_db.emplace(
      ue_index,
      ue_ctxt{ue_index, cell_index, this});
}

void scheduler_time_ai::rem_ue(du_ue_index_t ue_index)
{
  ue_history_db.erase(ue_index);
}

// ============================================================================
// Downlink scheduling
// ============================================================================

void scheduler_time_ai::compute_ue_dl_priorities(
    slot_point,
    slot_point pdsch_slot,
    span<ue_newtx_candidate> ue_candidates)
{
  if (!header_written) {
    rl_log_file
        << "system_slot,"
        << "frame,"
        << "slot,"
        << "ue_id,"
        << "reported_cqi,"
        << "buffer,"
        << "avg_rate,"
        << "estimated_rate,"
        << "pf_metric,"
        << "dqn_priority,"
        << "scheduled,"
        << "wait_slots,"
        << "allocated_prbs,"
        << "allocated_bytes,"
        << "mcs,"
        << "harq,"
        << "reward,"
        << "next_reported_cqi,"
        << "next_buffer,"
        << "next_avg_rate,"
        << "next_estimated_rate\n";
    header_written = true;
  }

  last_pdsch_slot = pdsch_slot;

  for (auto& u : ue_candidates) {
    du_ue_index_t ue_id = u.ue->ue_index();
    ue_ctxt& ctx = ue_history_db[ue_id];

    ctx.update_dl_avg(1);

    const ue_cell& ue_cc = u.ue->get_cc();

    double reported_cqi = static_cast<double>(
        ue_cc.channel_state_manager().get_wideband_cqi().to_uint());

    double buffer = static_cast<double>(
        u.ue->pending_dl_newtx_bytes());

    double avg_rate = ctx.total_dl_avg_rate();


    const search_space_id ss_id = to_search_space_id(2);
    const auto& ss_info = ue_cc.cfg().search_space(ss_id);

    const auto& pdsch_cfg = ss_info.get_pdsch_config(
        0,
        ue_cc.channel_state_manager().get_nof_dl_layers());

    auto mcs_opt = ue_cc.link_adaptation_controller()
                       .calculate_dl_mcs(pdsch_cfg.mcs_table);

    double estimated_rate = 1.0;

    if (mcs_opt.has_value()) {
      estimated_rate = ue_cc.get_estimated_dl_rate(
          pdsch_cfg,
          mcs_opt.value(),
          ss_info.dl_crb_lims.length());
    }

    double pf_metric = estimated_rate /
                       std::max(avg_rate, 1.0);

    pf_metric = std::clamp(pf_metric, 0.0, 100.0);

    // Log previous transition before resetting its outcome.
    if (ctx.has_prev) {
      ctx.prev_reward = ctx.reward;

      rl_log_file
          << ctx.prev_pdsch_slot.system_slot() << ","
          << ctx.prev_pdsch_slot.sfn() << ","
          << ctx.prev_pdsch_slot.slot_index() << ","
          << static_cast<int>(ue_id) << ","
          << ctx.prev_cqi << ","
          << ctx.prev_buffer << ","
          << ctx.prev_avg_rate << ","
          << ctx.prev_estimated_rate << ","
          << ctx.prev_pf_metric << ","
          << ctx.prev_priority << ","        
          << ctx.scheduled << ","
          << ctx.wait_slots << ","
          << ctx.allocated_prbs << ","
          << ctx.allocated_bytes << ","
          << static_cast<unsigned>(ctx.mcs) << ","
          << ctx.harq_retx << ","
          << ctx.prev_reward << ","
          << reported_cqi << ","
          << buffer << ","
          << avg_rate << ","
          << estimated_rate
          << "\n";
    }
    
    // If the UE was not scheduled in the previous slot,increase its waiting time.
    
    //if (ctx.allocated_bytes == 0)
       //ctx.wait_slots++;
    //else
       //ctx.wait_slots = 0;

    // Reset outcome for the new transition.
    ctx.scheduled = false;
    ctx.allocated_prbs = 0;
    ctx.allocated_bytes = 0;
    ctx.reward = 0.0;
    ctx.harq_id = 0;
    ctx.harq_retx = false;
    
    

    // PriorityNet state:
    // [CQI, log(buffer), log(avg_rate), log(estimated_rate), log(pf_metric)]
    std::array<float, 5> state = {
      static_cast<float>(reported_cqi / 15.0),
      static_cast<float>(std::log1p(buffer) / 16.2),
      static_cast<float>(std::log1p(avg_rate) / 7.3),
      static_cast<float>(std::log1p(estimated_rate) / 8.7),
      static_cast<float>(std::log1p(pf_metric) / 5.5)
     };
     
     
    float priority_score = dqn_inference(state);
    if (!std::isfinite(priority_score))
	  priority_score = 0.0f;
	  
    priority_score = std::clamp(priority_score, -1e6f, 1e6f);
    
    // Dynamic PF contribution
    double pf_norm = std::log1p(pf_metric) / 5.5;
    
    // Final scheduling priority
    double wait_bonus = std::min(ctx.wait_slots * 0.01, 0.15);
    double final_priority = 0.8 * priority_score + 0.2 * pf_norm + wait_bonus;
    
    u.priority = final_priority;


    // Store current state/action for the next transition.
    ctx.prev_pdsch_slot = pdsch_slot;
    ctx.prev_cqi = reported_cqi;
    ctx.prev_buffer = buffer;
    ctx.prev_avg_rate = avg_rate;
    ctx.prev_estimated_rate = estimated_rate;
    ctx.prev_pf_metric = pf_metric;
    ctx.prev_priority = final_priority;
    ctx.has_prev = true;
  }
}

// ============================================================================
// Uplink scheduling
// ============================================================================

void scheduler_time_ai::compute_ue_ul_priorities(
    slot_point,
    slot_point,
    span<ue_newtx_candidate> ue_candidates)
{
  for (auto& u : ue_candidates) {

    ue_ctxt& ctx =
        ue_history_db[u.ue->ue_index()];

    double avg_rate =
        ctx.total_ul_avg_rate();

    ctx.update_ul_avg(1);

    const ue_cell& ue_cc =
        u.ue->get_cc();

    // ------------------------------------------------------------------------
    // UL rate estimation
    // ------------------------------------------------------------------------

    const search_space_id ss_id =
        to_search_space_id(2);

    const auto& ss_info =
        ue_cc.cfg().search_space(ss_id);

    const auto& pusch_td_cfg =
        ss_info.pusch_time_domain_list.front();

    pusch_config_params pusch_cfg =
        get_pusch_config_f0_0_c_rnti(
            ue_cc.cfg().cell_cfg_common,
            &ue_cc.cfg(),
            ue_cc.cfg().cell_cfg_common.ul_cfg_common.init_ul_bwp,
            pusch_td_cfg,
            0,
            false);

    auto mcs =
        ue_cc.link_adaptation_controller()
            .calculate_ul_mcs(
                pusch_cfg.mcs_table,
                pusch_cfg.use_transform_precoder);

    double estimated_rate =
        ue_cc.get_estimated_ul_rate(
            pusch_cfg,
            mcs,
            ss_info.ul_crb_lims.length());

    // ------------------------------------------------------------------------
    // PF computation
    // ------------------------------------------------------------------------

    double priority =
        estimated_rate /
        std::max(avg_rate, 1.0);

    // ------------------------------------------------------------------------
    // Buffer awareness
    // ------------------------------------------------------------------------

    double buffer =
        static_cast<double>(
            u.ue->pending_ul_newtx_bytes());

    priority *=
        (1.0 + buffer / 1e6);

    // ------------------------------------------------------------------------
    // Safety
    // ------------------------------------------------------------------------

    if (!std::isfinite(priority)) {
      priority = 0.1;
    }

    u.priority =
        std::clamp(
            priority,
            1e-6,
            100.0);
  }
}

// ============================================================================
// Save DL grants
// ============================================================================

void scheduler_time_ai::save_dl_newtx_grants(span<const dl_msg_alloc> dl_grants)
{
  if (dl_grants.empty()) {
    return;
  }

  for (const auto& grant : dl_grants) {

    du_ue_index_t ue_id = grant.context.ue_index;
    ue_ctxt& ctx = ue_history_db[ue_id];

    // Scheduling outcome.
    ctx.scheduled = true;

    // Transport block size.
    ctx.allocated_bytes =
        grant.pdsch_cfg.codewords[0].tb_size_bytes;

    // PRB allocation.
    if (grant.pdsch_cfg.rbs.is_type1()) {
      ctx.allocated_prbs =
          grant.pdsch_cfg.rbs.type1().length();
    }

    // Actual MCS transition.
    ctx.prev_mcs = ctx.mcs;
    ctx.mcs = grant.pdsch_cfg.codewords[0].mcs_index.to_uint();

    // HARQ information.
    ctx.harq_id = grant.pdsch_cfg.harq_id;
    ctx.harq_retx = !grant.pdsch_cfg.codewords[0].new_data;

    // Updates DL average throughput and wait_slots.
    ctx.save_dl_alloc(ctx.allocated_bytes);

    // Throughput-oriented reward.
    double throughput_term =
        std::log1p(static_cast<double>(ctx.allocated_bytes)) / 10.0;

    double efficiency_term =
        std::min(static_cast<double>(ctx.allocated_prbs) / 51.0, 1.0);

    ctx.reward =
        0.8 * throughput_term +
        0.2 * efficiency_term;
  }
}

// ============================================================================
// Save UL grants
// ============================================================================

void scheduler_time_ai::save_ul_newtx_grants(
    span<const ul_sched_info> ul_grants)
    
{
  for (const auto& grant : ul_grants) {

    ue_history_db[
        grant.context.ue_index]
        .save_ul_alloc(
            grant.pusch_cfg.tb_size_bytes);
  }
}

// ============================================================================
// UE context constructor
// ============================================================================

scheduler_time_ai::ue_ctxt::ue_ctxt(
    du_ue_index_t ue_index_,
    du_cell_index_t cell_index_,
    const scheduler_time_ai* parent_) :
  ue_index(ue_index_),
  cell_index(cell_index_),
  parent(parent_),
  total_dl_avg_rate_(parent->exp_avg_alpha),
  total_ul_avg_rate_(parent->exp_avg_alpha)
{
}

// ============================================================================
// DL allocation bookkeeping
// ============================================================================

void scheduler_time_ai::ue_ctxt::save_dl_alloc(uint32_t total_alloc_bytes)
{
  allocated_bytes = total_alloc_bytes;
  dl_sum_alloc_bytes += total_alloc_bytes;

  if (total_alloc_bytes > 0)
    wait_slots = 0;
  else
    wait_slots++;
}


// ============================================================================
// UL allocation bookkeeping
// ============================================================================

void scheduler_time_ai::ue_ctxt::save_ul_alloc(
    unsigned alloc_bytes)
{
  ul_sum_alloc_bytes +=
      alloc_bytes;
}

// ============================================================================
// UL average-rate update
// ============================================================================

void scheduler_time_ai::ue_ctxt::update_ul_avg(
    unsigned nof_slots_elapsed)
{
  if (nof_slots_elapsed > 1) {
    total_ul_avg_rate_.push_zeros(
        nof_slots_elapsed - 1);
  }

  total_ul_avg_rate_.push(
      ul_sum_alloc_bytes);

  // Reset for next slot.
  ul_sum_alloc_bytes = 0;
}

// ============================================================================
// DL average-rate update
// ============================================================================

void scheduler_time_ai::ue_ctxt::update_dl_avg(
    unsigned nof_slots_elapsed)
{
  if (nof_slots_elapsed > 1) {
    total_dl_avg_rate_.push_zeros(
        nof_slots_elapsed - 1);
  }

  total_dl_avg_rate_.push(
      dl_sum_alloc_bytes);

  // Reset for next slot.
  dl_sum_alloc_bytes = 0;
}
