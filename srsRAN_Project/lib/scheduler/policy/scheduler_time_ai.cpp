#include "scheduler_time_ai.h"
#include "../support/csi_report_helpers.h"
#include "../ue_scheduling/grant_params_selector.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <cstdlib>
#include <iostream>
#include <stdexcept>

using namespace srsran;

// ===== NN WEIGHTS =====
static double W1[32][4];
static double W2[32][32];
static double W3[32];

static double B1_nn[32];
static double B2_nn[32];
static double B3_nn[1];


inline double relu(double x) {
  return x > 0.0 ? x : 0.0;
}

void load_weights(const std::string& path)
{
  std::ifstream file(path);

  if (!file.is_open()) {
    throw std::runtime_error("Failed to open weights file");
  }

  // W1 (32x4)
  for (int i = 0; i < 32; i++)
    for (int j = 0; j < 4; j++)
      file >> W1[i][j];

  // B1 (32)
  for (int i = 0; i < 32; i++)
    file >> B1_nn[i];

  // W2 (32x32)
  for (int i = 0; i < 32; i++)
    for (int j = 0; j < 32; j++)
      file >> W2[i][j];

  // B2 (32)
  for (int i = 0; i < 32; i++)
    file >> B2_nn[i];

  // W3 (32)
  for (int i = 0; i < 32; i++)
    file >> W3[i];

  // B3 (1)
  file >> B3_nn[0];
}


// ===== RL LOGGING =====
static std::string log_path = std::string(getenv("HOME")) + "/Simulation/logs/nn_scheduler_log.csv";
static std::ofstream rl_log_file(log_path, std::ios::app);
static bool header_written = false;




// ================================================================

scheduler_time_ai::scheduler_time_ai(const scheduler_ue_expert_config&, du_cell_index_t cell_index_) :cell_index(cell_index_)
{
  static bool loaded = false;

  if (!loaded) {
    std::string filepath = std::string(getenv("HOME")) + "/Simulation/weights.txt";
    std::cout << "Loading weights from: " << filepath << std::endl;

    load_weights(filepath);

    loaded = true;  
  }
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
    rl_log_file << "slot,ue_id,cqi,buffer,avg_rate,last_bytes,priority,tx_bytes\n";
    header_written = true;
  }

  last_pdsch_slot = pdsch_slot;//log

  // Clear buffer for new slot
  slot_log_buffer.clear();//log

  for (auto& u : ue_candidates) {

    ue_ctxt& ctx = ue_history_db[u.ue->ue_index()];
    ctx.update_dl_avg(1);
    const ue_cell& ue_cc = u.ue->get_cc();

    double cqi = 0.0;
    double buffer = (double)u.ue->pending_dl_newtx_bytes();
    double avg_rate = ctx.total_dl_avg_rate();
    double last_bytes = std::max(ctx.get_last_dl_bytes(), 1.0);

    // ================= CQI via MCS =================
    const search_space_id ss_id = to_search_space_id(2);
    const auto& ss_info = ue_cc.cfg().search_space(ss_id);

    const auto& pdsch_cfg =
        ss_info.get_pdsch_config(0, ue_cc.channel_state_manager().get_nof_dl_layers());

    auto mcs_opt = ue_cc.link_adaptation_controller().calculate_dl_mcs(pdsch_cfg.mcs_table);

    if (mcs_opt.has_value()) {
      cqi = (double)mcs_opt.value().to_uint();
    }

    // ================= ESTIMATED DL RATE =================
    double inst_rate = 1.0; // fallback

    if (mcs_opt.has_value()) {
      inst_rate = ue_cc.get_estimated_dl_rate(
          pdsch_cfg,
          mcs_opt.value(),
          ss_info.dl_crb_lims.length());
    }

    // ================= PF BASELINE =================
    double pf = inst_rate / (avg_rate + 1e-6);
    pf = std::clamp(pf, 0.0, 100.0);

 
    // ================= NN_MODEL =================
    //double ai = run_nn(cqi, buffer, avg_rate, last_bytes);
    double ai = ue_ctxt::run_nn(cqi, buffer, avg_rate, last_bytes);

    // Safety
    if (!std::isfinite(ai)) {
     ai = 0.0;
     }

    // Convert back from log
    //double tx_pred = std::exp(ai) - 1.0;
    double tx_pred = ai;

    // Clamp AFTER conversion
    tx_pred = std::clamp(tx_pred, 0.0, 1e7);

    // ================= COMBINED PRIORITY =================
    const double alpha = 0.4;  

    double priority = (1 - alpha) * pf + alpha * tx_pred;
    //double priority = pf * (1.0 + alpha * tx_pred / 1e5);
    

    // ================= SAFETY =================
    if (!std::isfinite(priority)) {
      priority = 0.1;
    }

    priority = std::clamp(priority, 1e-6, 1e6);

    u.priority = priority;

    // ================= LOG BUFFER =================
    slot_log_buffer[u.ue->ue_index()] = {
        cqi,
        buffer,
        avg_rate,
        last_bytes,
        priority,
        0   // tx_bytes filled later
    };
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

    // --- OPTIONAL: BUFFER BOOST ---
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
  int slot_id = last_pdsch_slot.slot_index();

  // ===== UPDATE TX BYTES =====
  for (const auto& grant : dl_grants) {

    uint32_t bytes = grant.pdsch_cfg.codewords[0].tb_size_bytes;
    du_ue_index_t ue_id = grant.context.ue_index;

    ue_history_db[ue_id].save_dl_alloc(bytes);

    // Update buffer entry
    if (slot_log_buffer.find(ue_id) != slot_log_buffer.end()) {
      slot_log_buffer[ue_id].tx_bytes = bytes;
    }
  }

  // ===== FINAL LOGGING (ONE ROW PER UE) =====
  for (const auto& [ue_id, entry] : slot_log_buffer) {

    rl_log_file << slot_id << ","
                << (int)ue_id << ","
                << entry.cqi << ","
                << entry.buffer << ","
                << entry.avg_rate << ","
                << entry.last_bytes << ","
                << entry.priority << ","
                << entry.tx_bytes
                << "\n";
  }

  // Clear after logging
  slot_log_buffer.clear();
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

double scheduler_time_ai::ue_ctxt::run_nn(
    double cqi, double buffer, double avg_rate, double last_bytes)
{
  double x[4];

  x[0] = (cqi - 19.5650219) / 7.8482252;
  //x[1] = (buffer - 1e7);**
  x[1] = buffer / 1e7;
  
  x[2] = (avg_rate - 669.139233) / 345.52287463;
  x[3] = last_bytes / 1e5;
  //x[3] = (last_bytes - 1.0);**

  double h1[32];
  for (int i = 0; i < 32; i++) {
    h1[i] = B1_nn[i];
    for (int j = 0; j < 4; j++) {
      h1[i] += W1[i][j] * x[j];
    }
    h1[i] = relu(h1[i]);
  }

  double h2[32];
  for (int i = 0; i < 32; i++) {
    h2[i] = B2_nn[i];
    for (int j = 0; j < 32; j++) {
      h2[i] += W2[i][j] * h1[j];
    }
    h2[i] = relu(h2[i]);
  }

  double out = B3_nn[0];
  for (int i = 0; i < 32; i++) {
    out += W3[i] * h2[i];
  }

  return out;
}
