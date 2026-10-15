/* SPDX-License-Identifier: Apache-2.0
 * RAVEL's transport ABI, implemented by a supplied source-reviewed binding.
 * This header contains no upstream physics implementation.
 */
#ifndef RAVEL_DM_DRIVER_H
#define RAVEL_DM_DRIVER_H
#include <stddef.h>
struct ravel_dm_channel {
    double fraction;
    const char *incoming[2], *outgoing[2];
};
struct ravel_dm_result {
    const char *candidate;
    double mass_gev, omega_h2, xf;
    double sigma_si_p_cm2, sigma_si_n_cm2, sigma_sd_p_cm2, sigma_sd_n_cm2;
    double sigma_v_today_cm3_s, channel_fraction_remainder;
    size_t channel_count;
    const struct ravel_dm_channel *channels;
};
/* Read the full supplied request, check the tool's particle inventory and
 * parameter conventions, then perform its requested calculations. Return
 * nonzero on a failed calculation. Logs go to stderr, never into JSON.
 * Cross sections and rates must already use the explicit transport units.
 * Bindings must state whether sigma_v_today is a velocity average or a fixed
 * velocity value, and match the supplied prescription before returning it.
 */
int ravel_dm_evaluate(const char *request_path, struct ravel_dm_result *result);
#endif
