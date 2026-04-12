#include "scheduler_time_ai.h"
#include "../support/csi_report_helpers.h"
#include "../ue_scheduling/grant_params_selector.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <random>
#include <array>
#include "dqn_weights.h"

using namespace srsran;
static constexpr double action_scale[5] = {0.8, 0.9, 1.0, 1.1, 1.2};

// ================= ACTIVATION =================
inline double relu(double x) {
  return x > 0.0 ? x : 0.0;
}
// ================= DQN INFERENCE =================
int dqn_inference(const std::array<float, 4>& x)
{
  double h1[64];

  for (int i = 0; i < 64; i++) {
    h1[i] = B1[i];
    for (int j = 0; j < 4; j++)
      h1[i] += W1[i][j] * x[j];
    h1[i] = relu(h1[i]);
  }

  double h2[64];

  for (int i = 0; i < 64; i++) {
    h2[i] = B2[i];
    for (int j = 0; j < 64; j++)
      h2[i] += W2[i][j] * h1[j];
    h2[i] = relu(h2[i]);
  }

  double q[5];

  for (int i = 0; i < 5; i++) {
    q[i] = B3[i];
    for (int j = 0; j < 64; j++)
      q[i] += W3[i][j] * h2[j];
  }

  int best = 0;
  for (int i = 1; i < 5; i++) {
    if (q[i] > q[best])
      best = i;
  }

  return best;
}



// ===== DQN LOGGING =====
static std::string log_path = std::string(getenv("HOME")) + "/Simulation/logs/DQN_scheduler_log.csv";
static std::ofstream rl_log_file(log_path, std::ios::app);
static bool header_written = false;

static std::mt19937 rng(42);
static std::uniform_int_distribution<int> action_dist(0, 4);



// ================================================================

scheduler_time_ai::scheduler_time_ai(const scheduler_ue_expert_config&, du_cell_index_t cell_index_) :cell_index(cell_index_)
{
  // No weights needed for DQN data collection
}

void scheduler_time_ai::add_ue(du_ue_index_t ue_index)
{
  ue_history_db.emplace(ue_index, ue_ctxt{ue_index, cell_index, this});
}

void scheduler_time_ai::rem_ue(du_ue_index_t ue_index)
{
  ue_history_db.erase(ue_index);
}


// ================= DL SCHEDULING =================
void scheduler_time_ai::compute_ue_dl_priorities(slot_point,
                                                 slot_point pdsch_slot,
                                                 span<ue_newtx_candidate> ue_candidates)
{
  if (!header_written) {
    rl_log_file << "slot,ue_id,"
            << "cqi,buffer,avg_rate,last_bytes,"
            << "action,"
            << "reward,"
            << "next_cqi,next_buffer,next_avg_rate,next_last_bytes\n";     
    header_written = true;
  }

  last_pdsch_slot = pdsch_slot;

   
  for (auto& u : ue_candidates) {

  du_ue_index_t ue_id = u.ue->ue_index();
  ue_ctxt& ctx = ue_history_db[ue_id];

  ctx.update_dl_avg(1);
  const ue_cell& ue_cc = u.ue->get_cc();

  double cqi = 0.0;
  double buffer = (double)u.ue->pending_dl_newtx_bytes();
  double avg_rate = ctx.total_dl_avg_rate();
  double last_bytes = std::max(ctx.get_last_dl_bytes(), 1.0);

  // ================= CQI =================
  const search_space_id ss_id = to_search_space_id(2);
  const auto& ss_info = ue_cc.cfg().search_space(ss_id);

  const auto& pdsch_cfg =
      ss_info.get_pdsch_config(0, ue_cc.channel_state_manager().get_nof_dl_layers());

  auto mcs_opt = ue_cc.link_adaptation_controller().calculate_dl_mcs(pdsch_cfg.mcs_table);

  if (mcs_opt.has_value()) {
    cqi = (double)mcs_opt.value().to_uint();
  }

  // ================= ESTIMATED RATE =================
  double inst_rate = 1.0;
  if (mcs_opt.has_value()) {
    inst_rate = ue_cc.get_estimated_dl_rate(
        pdsch_cfg,
        mcs_opt.value(),
        ss_info.dl_crb_lims.length());
  }

  //double pf = inst_rate / (avg_rate + 1e-6);
  double pf = inst_rate / std::max(avg_rate, 1.0);
  pf = std::clamp(pf, 0.0, 100.0);

  // ============================================================
  // ===== UPDATE NEXT STATE FROM PREVIOUS SLOT 
  // ============================================================
  //if (slot_log_buffer.find(ue_id) != slot_log_buffer.end()) {
    //auto& prev = slot_log_buffer[ue_id];

    //prev.next_cqi = cqi;
    //prev.next_buffer = buffer;
    //prev.next_avg_rate = avg_rate;
    //prev.next_last_bytes = last_bytes;
  //}

  
  //int action = action_dist(rng);
  std::array<float, 4> state = {
    static_cast<float>(cqi / 27.0),
    static_cast<float>(buffer / 1e7),
    static_cast<float>(avg_rate / 1000.0),
    static_cast<float>(last_bytes / 1000.0)
  };
  int action = dqn_inference(state);
  action = std::clamp(action, 0, 4);

  // Map action → priority
  //double priority = pf * (1.0 + action * 0.25);
  //double action_scale[5] = {0.8, 0.9, 1.0, 1.1, 1.2};
  double priority = pf * action_scale[action];

  // Safety
  if (!std::isfinite(priority)) {
    priority = 0.1;
  }

  priority = std::clamp(priority, 1e-6, 1e6);
  u.priority = priority;
  // ===== IF we have previous state → complete transition =====
  if (ctx.has_prev) {
     rl_log_file << last_pdsch_slot.slot_index() << ","
		      << (int)ue_id << ","
		      << ctx.prev_cqi << ","
		      << ctx.prev_buffer << ","
		      << ctx.prev_avg_rate << ","
		      << ctx.prev_last_bytes << ","
		      << ctx.prev_action << ","
		      << ctx.prev_reward << ","
		      << cqi << ","
		      << buffer << ","
		      << avg_rate << ","
		      << last_bytes
		      << "\n";
	}

  // ===== STORE CURRENT AS NEXT PREVIOUS =====
  ctx.prev_cqi = cqi;
  ctx.prev_buffer = buffer;
  ctx.prev_avg_rate = avg_rate;
  ctx.prev_last_bytes = last_bytes;
  ctx.prev_action = action;
  ctx.prev_reward = 0.0; // will be updated later
  ctx.has_prev = true;

  // ============================================================
  // ===== STORE CURRENT STATE =====
  // ============================================================
  
}

}  
  

// ================= UL SCHEDULING =================


void scheduler_time_ai::compute_ue_ul_priorities(slot_point,
                                                 slot_point pusch_slot,
                                                 span<ue_newtx_candidate> ue_candidates)
{
  for (auto& u : ue_candidates) {

    ue_ctxt& ctx = ue_history_db[u.ue->ue_index()];
    //average first
    double avg_rate = ctx.total_ul_avg_rate();
    
    //updating the next slot
    ctx.update_ul_avg(1);
    
    const ue_cell& ue_cc = u.ue->get_cc();

    // --- UL RATE ESTIMATION ---
    const search_space_id ss_id = to_search_space_id(2);
    const auto& ss_info = ue_cc.cfg().search_space(ss_id);

    const auto& pusch_td_cfg = ss_info.pusch_time_domain_list.front();

    pusch_config_params pusch_cfg =
        get_pusch_config_f0_0_c_rnti(
            ue_cc.cfg().cell_cfg_common,
            &ue_cc.cfg(),
            ue_cc.cfg().cell_cfg_common.ul_cfg_common.init_ul_bwp,
            pusch_td_cfg,
            0,   // no HARQ ACK bits
            false);

   
    auto mcs = ue_cc.link_adaptation_controller()
               .calculate_ul_mcs(pusch_cfg.mcs_table,
                                 pusch_cfg.use_transform_precoder);

    double estimated_rate =
     ue_cc.get_estimated_ul_rate(
        pusch_cfg, mcs, ss_info.ul_crb_lims.length());

    // --- PF METRIC ---
    double priority = estimated_rate / (avg_rate + 1e-6);

    // --- BUFFER BOOST ---
    double buffer = u.ue->pending_ul_newtx_bytes();
    priority *= (1.0 + buffer / 1e6);

    // --- SAFETY ---
    if (!std::isfinite(priority)) {
      priority = 0.1;
    }

    u.priority = std::clamp(priority, 1e-6, 100.0);
  }
}

// ================= HISTORY =================

void scheduler_time_ai::save_dl_newtx_grants(span<const dl_msg_alloc> dl_grants)
{
  // ===== STEP 1: Compute total bytes in this slot =====
  double total_bytes = 0.0;
  for (const auto& grant : dl_grants) {
    total_bytes += grant.pdsch_cfg.codewords[0].tb_size_bytes;
  }

  // ===== STEP 2: Assign normalized reward per UE =====
  for (const auto& grant : dl_grants) {

    uint32_t bytes = grant.pdsch_cfg.codewords[0].tb_size_bytes;
    du_ue_index_t ue_id = grant.context.ue_index;

    ue_history_db[ue_id].save_dl_alloc(bytes);

    ue_ctxt& ctx = ue_history_db[ue_id];

    // Normalized reward (share of total throughput)
    ctx.prev_reward = bytes / std::max(total_bytes, 1.0);
  }
}



void scheduler_time_ai::save_ul_newtx_grants(span<const ul_sched_info> ul_grants)
{
  for (const auto& grant : ul_grants) {
    ue_history_db[grant.context.ue_index].save_ul_alloc(
        grant.pusch_cfg.tb_size_bytes);
  }
}

// ================= UE CONTEXT =================

scheduler_time_ai::ue_ctxt::ue_ctxt(du_ue_index_t ue_index_,
                                    du_cell_index_t cell_index_,
                                    const scheduler_time_ai* parent_) :
  ue_index(ue_index_),
  cell_index(cell_index_),
  parent(parent_),
  total_dl_avg_rate_(parent->exp_avg_alpha),
  total_ul_avg_rate_(parent->exp_avg_alpha)
{
}

void scheduler_time_ai::ue_ctxt::save_dl_alloc(uint32_t total_alloc_bytes)
{
  dl_sum_alloc_bytes += total_alloc_bytes;
  total_dl_avg_rate_.push(dl_sum_alloc_bytes);
  dl_sum_alloc_bytes = 0;
}


void scheduler_time_ai::ue_ctxt::save_ul_alloc(unsigned alloc_bytes)
{
  // Always accumulate, even if zero
  ul_sum_alloc_bytes += alloc_bytes;
}

void scheduler_time_ai::ue_ctxt::update_ul_avg(unsigned nof_slots_elapsed)
{
  if (nof_slots_elapsed > 1) {
    total_ul_avg_rate_.push_zeros(nof_slots_elapsed - 1);
  }

  total_ul_avg_rate_.push(ul_sum_alloc_bytes);

  // reset for next slot
  ul_sum_alloc_bytes = 0;
}
void scheduler_time_ai::ue_ctxt::update_dl_avg(unsigned nof_slots_elapsed)
{
  if (nof_slots_elapsed > 1) {
    total_dl_avg_rate_.push_zeros(nof_slots_elapsed - 1);
  }

  total_dl_avg_rate_.push(dl_sum_alloc_bytes);

  dl_sum_alloc_bytes = 0;
}


