/*
 *
 * Copyright 2021-2026 Software Radio Systems Limited
 *
 * This file is part of srsRAN.
 *
 * srsRAN is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as
 * published by the Free Software Foundation, either version 3 of
 * the License, or (at your option) any later version.
 *
 * srsRAN is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * A copy of the GNU Affero General Public License can be found in
 * the LICENSE file in the top-level directory of this distribution
 * and at http://www.gnu.org/licenses/.
 *
 */

#include "scheduler_time_rr.h"
#include "../slicing/slice_ue_repository.h"

#include "../support/csi_report_helpers.h"
#include <fstream>
#include <cstdlib>
#include <iostream>
// ***
#include <map>

struct log_entry {
  double cqi;
  double buffer;
  double avg_rate;
  double last_bytes;
  double priority;
  double tx_bytes;
};

static std::map<int, log_entry> slot_log_buffer;
// ***
using namespace srsran;

// ##
// ===== RL LOGGING =====
static std::string log_path = std::string(getenv("HOME")) + "/Simulation/logs/rr_scheduler_log.csv";
static std::ofstream rl_log_file(log_path, std::ios::app);
static bool header_written = false;

scheduler_time_rr::scheduler_time_rr(const scheduler_ue_expert_config& expert_cfg_) : expert_cfg(expert_cfg_) {}

//void scheduler_time_rr::compute_ue_dl_priorities(slot_point               pdcch_slot,
//                                                 slot_point               pdsch_slot,
//                                                 span<ue_newtx_candidate> ue_candidates)
//{
 
  // We perform round-robin by assigning priorities based on the difference between the current slot and the last slot
  // the UE has been allocated.
//  for (ue_newtx_candidate& candidate : ue_candidates) {
//    candidate.priority = dl_alloc_count - ue_last_dl_alloc_count[candidate.ue->ue_index()];
    
//  }
//}
// **
void scheduler_time_rr::compute_ue_dl_priorities(slot_point pdcch_slot,
                                                 slot_point pdsch_slot,
                                                 span<ue_newtx_candidate> ue_candidates)
{
  //static bool header_written = false;

  if (!header_written) {
    
    rl_log_file << "slot,ue_id,cqi,buffer,avg_rate,last_bytes,priority,tx_bytes\n";
    header_written = true;
  }

  slot_log_buffer.clear();

  for (ue_newtx_candidate& candidate : ue_candidates) {
    //std::cout << "NEW LOG ACTIVE\n";  
    int ue_id = candidate.ue->ue_index();

    double priority = dl_alloc_count - ue_last_dl_alloc_count[ue_id];
    candidate.priority = priority;
    
    // ===== GET REAL METRICS =====
    const ue_cell& ue_cc = candidate.ue->get_cc();

    double cqi = 0.0;
    double buffer = (double)candidate.ue->pending_dl_newtx_bytes();
    double avg_rate = 0.0;
    double last_bytes = 0.0;

    // --- CQI via MCS ---
    const search_space_id ss_id = to_search_space_id(2);
    const auto& ss_info = ue_cc.cfg().search_space(ss_id);

    const auto& pdsch_cfg =
        ss_info.get_pdsch_config(0,      ue_cc.channel_state_manager().get_nof_dl_layers());

    auto mcs_opt =   ue_cc.link_adaptation_controller().calculate_dl_mcs(pdsch_cfg.mcs_table);

    if (mcs_opt.has_value()) {
      cqi = (double)mcs_opt.value().to_uint();
    }

    // STORE EVERYTHING 
    slot_log_buffer[ue_id] = {
      cqi,
      buffer,
      avg_rate,
      last_bytes,
      priority,
      0
    };
              
  }
}
// **


void scheduler_time_rr::compute_ue_ul_priorities(slot_point               pdcch_slot,
                                                 slot_point               pusch_slot,
                                                 span<ue_newtx_candidate> ue_candidates)
{
  // \ref compute_ue_dl_priorities
  for (ue_newtx_candidate& candidate : ue_candidates) {
    candidate.priority = ul_alloc_count - ue_last_ul_alloc_count[candidate.ue->ue_index()];
  }
}

void scheduler_time_rr::save_dl_newtx_grants(span<const dl_msg_alloc> dl_grants)
{
  if (dl_grants.empty()) {
    return;
  }
  int slot_id = dl_alloc_count; // ***
  
  
  for (const auto& grant : dl_grants) {
    int ue_id = grant.context.ue_index;

    ue_last_dl_alloc_count[ue_id] = dl_alloc_count;

    uint32_t bytes = grant.pdsch_cfg.codewords[0].tb_size_bytes;

    if (slot_log_buffer.find(ue_id) != slot_log_buffer.end()) {
      slot_log_buffer[ue_id].tx_bytes = bytes;
    }
  }

  // 
  for (const auto& [ue_id, entry] : slot_log_buffer) {
  
  rl_log_file << slot_id << ","
            << ue_id << ","
            << entry.cqi << ","
            << entry.buffer << ","
            << entry.avg_rate << ","
            << entry.last_bytes << ","
            << entry.priority << ","
            << entry.tx_bytes
            << "\n";
   
  }
  rl_log_file.flush(); 
  slot_log_buffer.clear();
  
  ++dl_alloc_count;
}

void scheduler_time_rr::save_ul_newtx_grants(span<const ul_sched_info> ul_grants)
{
  if (ul_grants.empty()) {
    return;
  }

  // Mark the count for the allocated UEs.
  for (const auto& grant : ul_grants) {
    ue_last_ul_alloc_count[grant.context.ue_index] = ul_alloc_count;
  }
  ++ul_alloc_count;
}
