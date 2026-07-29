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

#pragma once

#include "scheduler_policy.h"
#include "srsran/scheduler/config/scheduler_expert_config.h"

//new items added
#include <unordered_map>
#include <fstream>
#include "srsran/support/math/exponential_averager.h"


namespace srsran {

class scheduler_time_rr : public scheduler_policy
{
struct ue_log_context
{
  // Previous state
  double prev_cqi = 0;
  double prev_buffer = 0;
  double prev_avg_rate = 0;
  double prev_est_rate = 0;
  double prev_pf = 0;

  unsigned prev_priority = 0;

  bool has_prev = false;

  // Scheduling result 
  bool scheduled = false;

  uint32_t allocated_prbs = 0;
  uint32_t allocated_bytes = 0;

  uint8_t mcs = 0;
  uint8_t prev_mcs = 0;

  bool harq = false;

  double reward = 0;

  // Throughput history 
  exp_average_fast_start<double> avg_rate;

  uint32_t bytes_this_slot = 0;
  ue_log_context(): avg_rate(0.01){}
  
};
public:
  scheduler_time_rr(const scheduler_ue_expert_config& expert_cfg_);

  void add_ue(du_ue_index_t ue_index) override {}

  void rem_ue(du_ue_index_t ue_index) override {}

  void compute_ue_dl_priorities(slot_point               pdcch_slot,
                                slot_point               pdsch_slot,
                                span<ue_newtx_candidate> ue_candidates) override;

  void compute_ue_ul_priorities(slot_point               pdcch_slot,
                                slot_point               pusch_slot,
                                span<ue_newtx_candidate> ue_candidates) override;

  void save_dl_newtx_grants(span<const dl_msg_alloc> dl_grants) override;

  void save_ul_newtx_grants(span<const ul_sched_info> ul_grants) override;

private:
  const scheduler_ue_expert_config expert_cfg;

  // Tables to keep track of UE priorities.
  std::array<unsigned, MAX_NOF_DU_UES> ue_last_dl_alloc_count{};
  std::array<unsigned, MAX_NOF_DU_UES> ue_last_ul_alloc_count{};
  std::unordered_map<du_ue_index_t, ue_log_context> log_db;

  unsigned dl_alloc_count{0};
  unsigned ul_alloc_count{0};
  
  //slot bookkeeping
  slot_point last_pdsch_slot;
  uint64_t system_slot_counter = 0;


};

} // namespace srsran
