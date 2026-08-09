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

//additional files
#include "../support/csi_report_helpers.h"
#include "../ue_scheduling/grant_params_selector.h"

#include <fstream>
#include <cstdlib>
#include <algorithm>
#include <cmath>



using namespace srsran;

static std::string log_path = std::string(getenv("HOME")) + "/Oulun_Owls-Spring_Engineering_Challenge/logs/RR_scheduler_log.csv";

static std::ofstream rr_log(log_path,std::ios::app);

static bool header_written = false;

scheduler_time_rr::scheduler_time_rr(const scheduler_ue_expert_config& expert_cfg_) : expert_cfg(expert_cfg_) {}

void scheduler_time_rr::compute_ue_dl_priorities(slot_point               pdcch_slot,
                                                 slot_point               pdsch_slot,
                                                 span<ue_newtx_candidate> ue_candidates)
{
  //Writing the CSV header
  if (!header_written) {
  rr_log
      << "system_slot,"
      << "frame,"
      << "slot,"
      << "ue_id,"
      << "reported_cqi,"
      << "buffer,"
      << "avg_rate,"
      << "estimated_rate,"
      << "pf_metric,"
      << "rr_priority,"
      << "scheduled,"
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

  //saving the current slot information 
  last_pdsch_slot = pdsch_slot;
  system_slot_counter++;
  
  
  // We perform round-robin by assigning priorities based on the difference between the current slot and the last slot
  // the UE has been allocated.
  //for (ue_newtx_candidate& candidate : ue_candidates) {
    //candidate.priority = dl_alloc_count - ue_last_dl_alloc_count[candidate.ue->ue_index()];
  //}
  
  //new logic 
  for (ue_newtx_candidate& candidate : ue_candidates) {
    du_ue_index_t ue_id = candidate.ue->ue_index();

    auto& ctx = log_db[ue_id];
    
    
    //updating throughput
    ctx.avg_rate.push(ctx.bytes_this_slot);
    ctx.bytes_this_slot = 0;
    double avg_rate = ctx.avg_rate.get_average_value();
    
    //reading current UE Information
    const ue_cell& ue_cc = candidate.ue->get_cc();
    const auto reported_cqi =
    ue_cc.channel_state_manager().get_wideband_cqi();
    double cqi = reported_cqi.to_uint();
 
 
    double buffer = static_cast<double>(
        candidate.ue->pending_dl_newtx_bytes());
        
    const search_space_id ss_id = to_search_space_id(2);

    const auto& ss_info = ue_cc.cfg().search_space(ss_id);

    const auto& pdsch_cfg = ss_info.get_pdsch_config(0,
        ue_cc.channel_state_manager()
             .get_nof_dl_layers());

    auto mcs = ue_cc.link_adaptation_controller()
         .calculate_dl_mcs(pdsch_cfg.mcs_table);

    uint8_t current_mcs = 0;
    if (mcs.has_value()) {
        current_mcs = mcs.value().to_uint();
        ctx.mcs = current_mcs;
        }
    
    //estimating rate
    double estimated_rate = 1.0;

    if (mcs.has_value()) {

	estimated_rate = ue_cc.get_estimated_dl_rate(pdsch_cfg, mcs.value(),
		    ss_info.dl_crb_lims.length());
	}	

    //fairness metric
    double pf_metric = estimated_rate / std::max(avg_rate,1.0);
    
    //Computing RR priority
    unsigned rr_priority = dl_alloc_count - ue_last_dl_alloc_count[ue_id]; 
    candidate.priority = rr_priority;
    
    //Logging previous transition
    if (ctx.has_prev){
        rr_log
        << system_slot_counter << ","
        << pdsch_slot.sfn() << ","
        << pdsch_slot.slot_index() << ","

        << ue_id << ","

        << ctx.prev_cqi << ","
        << ctx.prev_buffer << ","
        << ctx.prev_avg_rate << ","
        << ctx.prev_est_rate << ","

        << ctx.prev_pf << ","

        << ctx.prev_priority << ","

        << ctx.scheduled << ","

        << ctx.allocated_prbs << ","

        << ctx.allocated_bytes << ","

        << unsigned(ctx.prev_mcs) << ","

        << ctx.harq << ","

        << ctx.reward << ","

        << cqi << ","

        << buffer << ","

        << avg_rate << ","

        << estimated_rate

        << "\n";
   }
   //rsetting
   ctx.scheduled = false;
   ctx.allocated_bytes = 0;
   ctx.allocated_prbs = 0;
   ctx.reward = 0;
   
   //saving current state
   ctx.prev_cqi = cqi;
   ctx.prev_buffer = buffer;
   ctx.prev_avg_rate = avg_rate;
   ctx.prev_est_rate = estimated_rate;
   ctx.prev_pf = pf_metric;
   ctx.prev_priority = rr_priority;
   ctx.prev_mcs = ctx.mcs;
   ctx.has_prev = true;
    
  }
}

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

  // Mark the count for the allocated UEs.
  for (const auto& grant : dl_grants) {
    auto& ctx = log_db[grant.context.ue_index];
    ctx.scheduled = true;

    ctx.allocated_bytes = grant.pdsch_cfg.codewords[0].tb_size_bytes;
    ctx.bytes_this_slot += ctx.allocated_bytes;

    // reward left raw for now
    ctx.reward = ctx.allocated_bytes;
  
    ue_last_dl_alloc_count[grant.context.ue_index] = dl_alloc_count;
  }
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
